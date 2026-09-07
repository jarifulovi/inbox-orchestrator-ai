import ctypes
import gc
import os
import platform


def apply_thread_limits() -> None:
    """Sets CPU thread limits for PyTorch, OpenMP, MKL, and OpenBLAS to prevent CPU/RAM allocation spikes."""
    thread_limit = "2"
    for var in [
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ]:
        if var not in os.environ:
            os.environ[var] = thread_limit


def force_garbage_collection() -> None:
    """
    Forces Python garbage collection and triggers Linux glibc malloc_trim
    to release unreferenced PyTorch / C++ memory arenas back to the OS kernel.
    """
    gc.collect()
    if platform.system() == "Linux":
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass
