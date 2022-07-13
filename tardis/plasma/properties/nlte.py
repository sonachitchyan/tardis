import logging
import os

import numpy as np
import pandas as pd

from tardis.plasma.properties.base import (
    PreviousIterationProperty,
    ProcessingPlasmaProperty,
)
from tardis.plasma.properties.ion_population import PhiSahaNebular

__all__ = [
    "PreviousElectronDensities",
    "PreviousBetaSobolev",
    "HeliumNLTE",
    "HeliumNumericalNLTE",
]

logger = logging.getLogger(__name__)


class PreviousElectronDensities(PreviousIterationProperty):
    """
    Attributes
    ----------
    previous_electron_densities : The values for the electron densities converged upon in the previous iteration.
    """

    outputs = ("previous_electron_densities",)

    def set_initial_value(self, kwargs):
        initial_value = pd.Series(
            1000000.0,
            index=kwargs["abundance"].columns,
        )
        self._set_initial_value(initial_value)


class PreviousBetaSobolev(PreviousIterationProperty):
    """
    Attributes
    ----------
    previous_beta_sobolev : The beta sobolev values converged upon in the previous iteration.
    """

    outputs = ("previous_beta_sobolev",)

    def set_initial_value(self, kwargs):
        initial_value = pd.DataFrame(
            1.0,
            index=kwargs["atomic_data"].lines.index,
            columns=kwargs["abundance"].columns,
        )
        self._set_initial_value(initial_value)


class HeliumNLTE(ProcessingPlasmaProperty):
    outputs = ("helium_population",)

    @staticmethod
    def calculate(
        level_boltzmann_factor,
        ionization_data,
        beta_rad,
        g,
        g_electron,
        w,
        t_rad,
        t_electrons,
        delta,
        zeta_data,
        number_density,
        partition_function,
    ):
        """
        Updates all of the helium level populations according to the helium NLTE recomb approximation.
        """
        helium_population = level_boltzmann_factor.loc[2].copy()
        # He I excited states
        he_one_population = HeliumNLTE.calculate_helium_one(
            g_electron, beta_rad, ionization_data, level_boltzmann_factor, g, w
        )
        helium_population.loc[0].update(he_one_population)
        # He I ground state
        helium_population.loc[0, 0] = 0.0
        # He II excited states
        he_two_population = level_boltzmann_factor.loc[2, 1].mul(
            (g.loc[2, 1, 0] ** (-1.0))
        )
        helium_population.loc[1].update(he_two_population)
        # He II ground state
        helium_population.loc[1, 0] = 1.0
        # He III states
        helium_population.loc[2, 0] = HeliumNLTE.calculate_helium_three(
            t_rad,
            w,
            zeta_data,
            t_electrons,
            delta,
            g_electron,
            beta_rad,
            ionization_data,
            g,
        )
        #        unnormalised = helium_population.sum()
        #        normalised = helium_population.mul(number_density.ix[2] / unnormalised)
        #        helium_population.update(normalised)
        return helium_population

    @staticmethod
    def calculate_helium_one(
        g_electron, beta_rad, ionization_data, level_boltzmann_factor, g, w
    ):
        """
        Calculates the He I level population values, in equilibrium with the He II ground state.
        """
        return (
            level_boltzmann_factor.loc[2, 0]
            * (1.0 / (2 * g.loc[2, 1, 0]))
            * (1 / g_electron)
            * (1 / (w**2.0))
            * np.exp(ionization_data.loc[2, 1] * beta_rad)
        )

    @staticmethod
    def calculate_helium_three(
        t_rad,
        w,
        zeta_data,
        t_electrons,
        delta,
        g_electron,
        beta_rad,
        ionization_data,
        g,
    ):
        """
        Calculates the He III level population values.
        """
        zeta = PhiSahaNebular.get_zeta_values(zeta_data, 2, t_rad)[1]
        he_three_population = (
            2
            * (float(g.loc[2, 2, 0]) / g.loc[2, 1, 0])
            * g_electron
            * np.exp(-ionization_data.loc[2, 2] * beta_rad)
            * w
            * (delta.loc[2, 2] * zeta + w * (1.0 - zeta))
            * (t_electrons / t_rad) ** 0.5
        )
        return he_three_population


class HeliumNumericalNLTE(ProcessingPlasmaProperty):
    """
    IMPORTANT: This particular property requires a specific numerical NLTE
    solver and a specific atomic dataset (neither of which are distributed
    with Tardis) to work.
    """

    outputs = ("helium_population",)

    def __init__(self, plasma_parent, heating_rate_data_file):
        super(HeliumNumericalNLTE, self).__init__(plasma_parent)
        self._g_upper = None
        self._g_lower = None
        self.heating_rate_data = np.loadtxt(heating_rate_data_file, unpack=True)

    def calculate(
        self,
        ion_number_density,
        electron_densities,
        t_electrons,
        w,
        lines,
        j_blues,
        levels,
        level_boltzmann_factor,
        t_rad,
        zeta_data,
        g_electron,
        delta,
        partition_function,
        ionization_data,
        beta_rad,
        g,
        time_explosion,
    ):
        logger.info("Performing numerical NLTE He calculations.")
        if len(j_blues) == 0:
            return None
        # Outputting data required by SH module
        for zone, _ in enumerate(electron_densities):
            with open(
                f"He_NLTE_Files/shellconditions_{zone}.txt", "w"
            ) as output_file:
                output_file.write(ion_number_density.loc[2].sum()[zone])
                output_file.write(electron_densities[zone])
                output_file.write(t_electrons[zone])
                output_file.write(self.heating_rate_data[zone])
                output_file.write(w[zone])
                output_file.write(time_explosion)
                output_file.write(t_rad[zone])
                output_file.write(self.plasma_parent.v_inner[zone])
                output_file.write(self.plasma_parent.v_outer[zone])

        for zone, _ in enumerate(electron_densities):
            with open(
                f"He_NLTE_Files/abundances_{zone}.txt", "w"
            ) as output_file:
                for element in range(1, 31):
                    try:
                        number_density = (
                            ion_number_density[zone].loc[element].sum()
                        )
                    except:
                        number_density = 0.0
                        logger.debug(
                            f"Number Density could not be calculated. Setting Number Density to {number_density}"
                        )
                    output_file.write(number_density)

            helium_lines = lines[lines["atomic_number"] == 2]
            helium_lines = helium_lines[helium_lines["ion_number"] == 0]
        for zone, _ in enumerate(electron_densities):
            with open(
                f"He_NLTE_Files/discradfield_{zone}.txt", "w"
            ) as output_file:
                j_blues = pd.DataFrame(j_blues, index=lines.index)
                helium_j_blues = j_blues[zone].loc[helium_lines.index]
                for value in helium_lines.index:
                    if helium_lines.level_number_lower.loc[value] < 35:
                        output_file.write(
                            int(helium_lines.level_number_lower.loc[value] + 1),
                            int(helium_lines.level_number_upper.loc[value] + 1),
                            j_blues[zone].loc[value],
                        )
        # Running numerical simulations
        for zone, _ in enumerate(electron_densities):
            os.rename(
                f"He_NLTE_Files/abundances{zone}.txt",
                "He_NLTE_Files/abundances_current.txt",
            )
            os.rename(
                f"He_NLTE_Files/shellconditions{zone}.txt",
                "He_NLTE_Files/shellconditions_current.txt",
            )
            os.rename(
                f"He_NLTE_Files/discradfield{zone}.txt",
                "He_NLTE_Files/discradfield_current.txt",
            )
            os.system("nlte-solver-module/bin/nlte_solvertest >/dev/null")
            os.rename(
                "He_NLTE_Files/abundances_current.txt",
                f"He_NLTE_Files/abundances{zone}.txt",
            )
            os.rename(
                "He_NLTE_Files/shellconditions_current.txt",
                f"He_NLTE_Files/shellconditions{zone}.txt",
            )
            os.rename(
                "He_NLTE_Files/discradfield_current.txt",
                f"He_NLTE_Files/discradfield{zone}.txt",
            )
            os.rename("debug_occs.dat", f"He_NLTE_Files/occs{zone}.txt")
        # Reading in populations from files
        helium_population = level_boltzmann_factor.loc[2].copy()
        for zone, _ in enumerate(electron_densities):
            with open(
                f"He_NLTE_Files/discradfield{zone}.txt", "r"
            ) as read_file:
                for level in range(0, 35):
                    level_population = read_file.readline()
                    level_population = float(level_population)
                    helium_population[zone].loc[0, level] = level_population
                helium_population[zone].loc[1, 0] = float(read_file.readline())
        # Performing He LTE level populations (upper two energy levels,
        # He II excited states, He III)
        he_one_population = HeliumNLTE.calculate_helium_one(
            g_electron,
            beta_rad,
            partition_function,
            ionization_data,
            level_boltzmann_factor,
            electron_densities,
            g,
            w,
            t_rad,
            t_electrons,
        )
        helium_population.loc[0, 35].update(he_one_population.loc[35])
        helium_population.loc[0, 36].update(he_one_population.loc[36])

        he_two_population = level_boltzmann_factor.loc[2, 1, 1:].mul(
            (g.loc[2, 1, 0] ** (-1)) * helium_population.loc[s1, 0]
        )
        helium_population.loc[1, 1:].update(he_two_population)

        helium_population.loc[2, 0] = HeliumNLTE.calculate_helium_three(
            t_rad,
            w,
            zeta_data,
            t_electrons,
            delta,
            g_electron,
            beta_rad,
            partition_function,
            ionization_data,
            electron_densities,
        )
        unnormalised = helium_population.sum()
        normalised = helium_population.mul(
            ion_number_density.loc[2].sum() / unnormalised
        )
        helium_population.update(normalised)
        return helium_population

class RateEquationSolver(ProcessingPlasmaProperty):
    outputs = ("nlte_ion_population", "nlte_electron_densities")

    def calculate(self, phi, number_density):
        initial_electron_densities = number_density.sum(axis=0)
        atomic_numbers = number_density.index
        populations, index = self.initialize_populations_frame(
            atomic_numbers, phi.columns
        )
        electron_densities = np.zeros(len(phi.columns))
        for i, shell in enumerate(phi.columns):
            solution_vector = self.prepare_solution_vector(
                number_density[shell]
            )
            first_guess = self.prepare_first_guess(
                number_density[shell], initial_electron_densities[shell]
            )
            solution = root(
                self.population_objective_function,
                first_guess,
                args=(phi[shell], number_density[shell], solution_vector),
                jac=True,
            )
            assert solution.success
            electron_densities[i] = solution.x[-1]
            populations[i] = solution.x[:-1]
        populations[populations < 0] = 0

        # TODO: check that number conservation still has high precision, if not, yell
        index = pd.MultiIndex.from_arrays(
            [index[:, 0], index[:, 1]], names=phi.index.names
        )
        populations = pd.DataFrame(
            populations.T, index=index, columns=phi.columns
        )
        electron_densities = pd.Series(electron_densities, index=phi.columns)
        return populations, electron_densities

    def initialize_populations_frame(self, atomic_numbers, columns):
        populations_frame_size = (atomic_numbers.values + 1).sum()
        index = np.zeros((populations_frame_size, 2), dtype=np.int)
        counter = 0
        for atomic_number in atomic_numbers:
            for i in range(atomic_number + 1):
                index[counter] = (atomic_number, i)
                counter += 1
        solutions = np.empty(
            (len(columns), populations_frame_size), dtype=np.float64
        )
        return solutions, index

    def create_rate_equation_matrix(
        self, phi, electron_density, number_density
    ):
        lte_rate_matrix_diag = []
        last_row = []
        atomic_numbers = number_density.index
        for atomic_number in atomic_numbers:
            phi_block = phi.loc[atomic_number]
            lte_rate_matrix_block = self.lte_rate_matrix_block(
                phi_block, electron_density
            )
            lte_rate_matrix_diag.append(lte_rate_matrix_block)
            last_row.append(np.arange(0, atomic_number + 1))
        lte_rate_matrix = block_diag(*lte_rate_matrix_diag, -1)
        last_row_vector = np.hstack(last_row)
        lte_rate_matrix[-1, :-1] = last_row_vector
        return lte_rate_matrix

    def lte_rate_matrix_block(self, phi_block, electron_density):
        lte_rate_vector_block = np.hstack([-phi_block, 1.0])
        lte_rate_matrix_block = np.diag(lte_rate_vector_block)
        n_e_initial = np.ones(len(phi_block)) * electron_density
        n_e_matrix = np.diag(n_e_initial, 1)
        lte_rate_matrix_block += n_e_matrix
        lte_rate_matrix_block[-1, :] = 1.0
        return lte_rate_matrix_block

    def solution_vector_block(self, atomic_number, number_density):
        solution_vector = np.zeros(atomic_number + 1)
        solution_vector[-1] = number_density
        return solution_vector

    def prepare_solution_vector(self, number_density):
        atomic_numbers = number_density.index
        solution_array = []
        for atomic_number in atomic_numbers:
            solution_array.append(
                self.solution_vector_block(
                    atomic_number, number_density.loc[atomic_number]
                )
            )
        solution_vector = np.hstack(solution_array + [0])
        return solution_vector

    def population_objective_function(
        self, populations, phi, number_density, solution_vector
    ):
        electron_density = populations[-1]
        rate_matrix = self.create_rate_equation_matrix(
            phi, electron_density, number_density
        )
        jacobian_matrix = self.jacobian_matrix(
            populations, rate_matrix, number_density
        )
        return (
            np.dot(rate_matrix, populations) - solution_vector,
            jacobian_matrix,
        )

    def prepare_phi(self, phi):
        phi[phi == 0.0] = 1.0e-10 * phi[phi > 0.0].min().min()
        return phi

    def prepare_first_guess(self, number_density, electron_density):
        atomic_numbers = number_density.index
        array_size = (number_density.index.values + 1).sum() + 1
        first_guess = np.zeros(array_size)
        index = 1
        for atomic_number in atomic_numbers:
            first_guess[index] = number_density.loc[atomic_number]
            index += atomic_number + 1
        first_guess[-1] = electron_density
        return first_guess

    def jacobian_matrix(self, populations, lte_rate_matrix, number_density):
        atomic_numbers = number_density.index
        index = atomic_numbers[0]
        jacobian_matrix = lte_rate_matrix.copy()
        jacobian_matrix[:-1, -1] = populations[1:]
        jacobian_matrix[index, -1] = 0
        for atomic_number in atomic_numbers[1:]:
            index += 1 + atomic_number
            jacobian_matrix[index, -1] = 0

        return jacobian_matrix