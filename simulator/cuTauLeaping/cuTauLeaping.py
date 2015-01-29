import string
import numpy

import pycuda.driver as cuda
import pycuda.autoinit
import pycuda.tools as cuda_tools
from pycuda.compiler import SourceModule
import pycuda.gpuarray as gpuarray

from parser import TlParser
import P1_P2
import P3


# def cu_tau_leaping(sbml_model, sim_info):
def cu_tau_leaping(sbml_model):
    # 2. A, V, V_t, V_bar, H, H_type <- CalculateDataStructures(MA, MB, x_0, c)
    my_args = TlParser.parse(sbml_model)

    P1_P2_template = string.Template(P1_P2.kernel)
    P1_P2_code = template_to_code(P1_P2_template, my_args)

    P3_template = string.Template(P3.kernel)
    P3_code = template_to_code(P3_template, my_args)

    P1_P2_kernel = SourceModule(P1_P2_code, no_extern_c=True)
    P3_kernel = SourceModule(P3_code, no_extern_c=True)

    # 3. LoadDataOnGPU( A, V, V_t, V_bar, H, H_type, x_0, c )
    LoadDataOnGPU(my_args, P1_P2_kernel)
    LoadDataOnGPU(my_args, P3_kernel)

    # 4. AllocateDataOnGPU( t, x, O, E, Q )
    d_x, d_O, d_Q, d_t, d_F = AllocateDataOnGPU(my_args)
    d_rng = get_rng_states(my_args.U)

    # 5. gridSize, blockSize <- DistributeWorkload(U)
    grid_size, block_size = CalculateSizes(my_args)

    # 6. repeat
    TerminSimulations = 0
    while TerminSimulations != my_args.U:
        # 7. Kernel_p1-p2<<<gridSize, blockSize>>>
        # 8.    ( A, V, V_t, V_bar, H, H_type, x, c, I, E, O, Q, t )
        kernel_P1_P2 = P1_P2_kernel.get_function('kernel_P1_P2')
        kernel_P1_P2(d_x, d_O, d_Q, d_t, d_F, d_rng,
                     grid=(int(grid_size), 1, 1), block=(int(block_size), 1, 1))

        # x, E, O, Q, t, F = GetGlobals(d_x, d_E, d_O, d_Q, d_t, d_F)
        # FreeMemoryOnGPU(d_x, d_E, d_O, d_Q, d_t, d_F)

        # 9. Kernel_p3<<<gridSize, blockSize>>>
        # 10.   ( A, V, x, c, I, E, O, Q, t )

        # d_x, d_E, d_O, d_Q, d_t, d_F  = AllocateGlobals(x, E, O, Q, t, F)

        kernel_P3 = P3_kernel.get_function('kernel_P3')
        kernel_P3(d_x, d_O, d_Q, d_t, d_F, d_rng, grid=(int(grid_size), 1, 1),
                  block=(int(block_size), 1, 1))

        # x, O, Q, t, F = GetGlobals(d_x, d_O, d_Q, d_t, d_F)

        # FreeMemoryOnGPU(d_x, d_E, d_O, d_Q, d_t, d_F)

        # 11. TerminSimulations <- Kernel_p4 <<<gridSize,blockSize>>>(Q)
        Q = gpuarray.sum(d_Q).get()
        # Q = pycuda.gpuarray.sum(d_Q).get()
        TerminSimulations = -Q

    # 12. unitl TerminSimulations = U
    O = d_O.get()
    return O[0]

# 13. end procedure

def LoadDataOnGPU(tl_args, module):
    d_A = module.get_global('d_A')[0]
    cuda.memcpy_htod(d_A, tl_args.A)

    d_V = module.get_global('d_V')[0]
    cuda.memcpy_htod(d_V, tl_args.V)

    d_H = module.get_global('d_H')[0]
    cuda.memcpy_htod(d_H, tl_args.H)

    d_H_type = module.get_global('d_H_type')[0]
    cuda.memcpy_htod(d_H_type, tl_args.H_type)

    d_c = module.get_global('d_c')[0]
    cuda.memcpy_htod(d_c, tl_args.c)

    d_I = module.get_global('d_I')[0]
    cuda.memcpy_htod(d_I, tl_args.I)

    d_E = module.get_global('d_E')[0]
    cuda.memcpy_htod(d_E, tl_args.E)


def GetGlobals(d_x, d_O, d_Q, d_t, d_F):
    x = d_x.get()
    O = d_O.get()
    Q = d_Q.get()
    t = d_t.get()
    F = d_F.get()
    return x, O, Q, t, F


def AllocateGlobals(x, O, Q, t, F):
    d_t = gpuarray.to_gpu(t)
    d_x = gpuarray.to_gpu(x)
    d_O = gpuarray.to_gpu(O)
    d_Q = gpuarray.to_gpu(Q)
    d_F = gpuarray.to_gpu(F)

    return d_x, d_O, d_Q, d_t, d_F


def AllocateDataOnGPU(tl_args):
    t = numpy.zeros(tl_args.U, numpy.float32)

    x = numpy.ones([tl_args.U, tl_args.N], numpy.uint32)
    for i in range(tl_args.U):
        x[i] = tl_args.x_0

    O = numpy.zeros([tl_args.kappa, tl_args.ita, tl_args.U], numpy.uint32)

    Q = numpy.zeros(tl_args.U, numpy.int16)

    F = numpy.zeros(tl_args.U, numpy.uint32)

    return AllocateGlobals(x, O, Q, t, F)


def FreeMemoryOnGPU(d_x, d_O, d_Q, d_t, d_F):
    d_x.gpudata.free()
    d_O.gpudata.free()
    d_Q.gpudata.free()
    d_t.gpudata.free()
    d_F.gpudata.free()

def CalculateSizes(tl_args):
    import math

    max_threads_per_block = cuda_tools.DeviceData().max_threads
    max_shared_mem = cuda_tools.DeviceData().shared_memory
    warp_size = cuda_tools.DeviceData().warp_size

    # T <= floor(MAX_shared / (13M + 8N)) from cuTauLeaping paper eq (5)
    threads_per_block = math.floor(
        max_shared_mem / (13 * tl_args.M + 8 * tl_args.N))

    # optimal T is a multiple of warp size
    max_optimal_threads_per_block = min(
        math.floor(threads_per_block / warp_size) * warp_size,
        max_threads_per_block)

    blocks = math.ceil(tl_args.U / 256)


    # grid size is equal to the number of blocks we need
    # grid_size = math.ceil(tl_args.U / optimal_threads_per_block)

    return blocks, 256


def template_to_code(template, args):
    code = template.substitute(A_SIZE=args.A_size,
                               V_SIZE=args.V_size,
                               V_T_SIZE=args.V_t_size,
                               V_BAR_SIZE=args.V_bar_size,
                               SPECIES_NUM=args.N,
                               THREAD_NUM=args.U,
                               PARAM_NUM=len(args.c),
                               REACT_NUM=args.M,
                               KAPPA=args.kappa,
                               ITA=args.ita,
                               N_C=args.n_c,
                               ETA=args.eta,
                               T_MAX=args.t_max,
                               BLOCK_SIZE=256,
                               UPDATE_PROPENSITIES=args.hazards)
    return code


def get_rng_states(size):
    from pycuda import characterize

    init_rng_src = """
    #include <curand_kernel.h>

    extern "C"
    {

    __global__ void init_rng(int nthreads, curandStateMRG32k3a *s)
    {
        int tid = threadIdx.x + (blockIdx.x * blockDim.x);

        if (tid >= nthreads)
        {
            return;
        }

        curand_init(tid, 0, 0, &s[tid]);
    }

    } // extern "C"
    """

    rng_states = cuda.mem_alloc(
        size * characterize.sizeof('curandStateMRG32k3a',
                                   '#include <curand_kernel.h>'))

    module = pycuda.compiler.SourceModule(init_rng_src, no_extern_c=True)
    init_rng = module.get_function('init_rng')

    init_rng(numpy.int32(size), rng_states, numpy.uint64(0), block=(64, 1, 1),
             grid=(size // 64 + 1, 1))

    return rng_states

##########
# TEST
##########
import libsbml

# sbml_file = '/home/sandy/Downloads/plasmid_stability.xml'
# sbml_file = '/home/sandy/Downloads/elowitz_repressilator1_sbml.xml'
sbml_file = '/home/sandy/Downloads/simple_sbml.xml'
# sbml_file = '/home/sandy/Documents/Code/cuda-sim-code/examples/ex02_p53' \
# '/p53model.xml'
reader = libsbml.SBMLReader()
document = reader.readSBML(sbml_file)
# check the SBML for errors
error_count = document.getNumErrors()
if error_count > 0:
    raise UserWarning(error_count + ' errors in SBML file: ' + open_file_.name)
sbml_model = document.getModel()

O = cu_tau_leaping(sbml_model)

import matplotlib.pyplot as plt

num_bins = 500
# the histogram of the data
n, bins, patches = plt.hist(O[1], num_bins, normed=1, facecolor='green',
                            alpha=0.5)
plt.axis([10, 90, 0, 0.07])
plt.subplots_adjust(left=0.15)
plt.show()