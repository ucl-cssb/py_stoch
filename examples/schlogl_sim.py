import libsbml
from mod.simulator import cuTauLeaping
import sim_maker


##
## GET SBML MODEL ##
##
sbml_file = '/home/sandy/Documents/Code/py_stoch/examples/schlogl_sbmlv2.xml'
reader = libsbml.SBMLReader()
document = reader.readSBML(sbml_file)
# check the SBML for errors
error_count = document.getNumErrors()
if (error_count > 0):
    raise UserWarning(str(error_count) + ' errors in SBML file: ' +
                      sbml_file)
sbml_model = document.getModel()

##
## SIMULATOR PARAMETERS
##   I don't think it would be useful for any of these parameters to be sweepable
output_species = [0]  # A list of indices of the species you want to record.
                      # Indices are 0-based in the order they are listed in the
                      # given SBML file.
duration = 10  # Length of the simulation in arbitrary units
num_output_time_points = 2  # Number of points that you want to record the state
                            # of the system at. The points are uniformly
                            # distributed, starting from 0, across the duration
                            # of the simulation.
num_simulations = 25600  # Number of times you want to run each simulation setup.

##
## SIMULATION PARAMETERS
##   both of these parameter sets are sweepable
#
# Initial amounts of each species. The position in the list maps to the order
# the species are listed in the given SBML file. Each position must be a list
# containing one or more values. If more than one value is given for a species,
# simulations will be run for each combination of initial values.
# e.g. [[1], [2]] or [[1, 2, 3], [4]] etc.
species_init = [[250]]
# Parameter values. See description for "species_init" for details.
parameters = [[0.0000003], [0.0001], [0.0009, 0.001, 0.0011, 0.0012], [3.5],
              [100000], [200000]]

# Produce a list of all combinations of simulation from the given parameters
tl_args_list = sim_maker.TLArgsList.make_list(sbml_model, species_init,
                                              parameters, output_species,
                                              duration, num_output_time_points,
                                              num_simulations)

g_args_list = sim_maker.TLArgsList.make_list(sbml_model, species_init,
                                             parameters, output_species,
                                             duration, num_output_time_points,
                                             num_simulations, gillespie=1)

##
## RUN A SIMULATIONS
##
#TODO think about best way to store results.
tl_results = []
for args_idx, args in enumerate(tl_args_list):
    simulator = cuTauLeaping.CuTauLeaping()
    tl_results.append(simulator.run(args))

g_results = []
for args_idx, args in enumerate(g_args_list):
    simulator = cuTauLeaping.CuTauLeaping()
    new_result = simulator.run(args)
    g_results.append(new_result)


#####
#   RESULTS PLOTTING
#
import matplotlib.pyplot as plt
from scipy import stats
import numpy
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d import Axes3D

species_idx = 0
plt_range = numpy.arange(0, 800, 1)

fig = plt.figure(1)
data_TL = []
data_G = []
for result_idx in range(4):
    density_TL = stats.gaussian_kde(tl_results[result_idx][species_idx][1])
    density_G = stats.gaussian_kde(g_results[result_idx][species_idx][1])
    data_TL.append(list(zip(plt_range, density_TL(plt_range))))
    data_G.append(list(zip(plt_range, density_G(plt_range))))

poly_TL = PolyCollection(data_TL)
poly_TL.set_alpha(0.5)
poly_TL.set_color('red')

poly_G = PolyCollection(data_G)
poly_G.set_alpha(0.5)
poly_G.set_color('blue')

ax = fig.gca(projection='3d')
ax.set_xlabel('species_0')
# ax.set_ylabel('time')
ax.set_xlim3d(0, 800)
ax.set_ylim3d(0, 5)
ax.set_zlabel('proportion')
ax.set_zlim3d(0, 0.01)

ax.add_collection3d(poly_TL, zs=numpy.arange(1, 10, 1), zdir='y')
ax.add_collection3d(poly_G, zs=numpy.arange(1, 10, 1), zdir='y')
plt.show()

