"""PulCeq to TOPPE converter."""

__all__ = ["ceq2files"]

from types import SimpleNamespace

import numpy as np

from . import _interp


def ceq2files(
    sequence_name: str,
    ceqstruct: SimpleNamespace,
    sys: SimpleNamespace,
    ignore_trigger: bool = False,
    sequence_path: str = None,
    verbose: bool = False,
):
    """
    Write a PulCeq struct to a set of files that can be executed
    on GE scanners using the TOPPE interpreter (v6).

    Parameters
    ----------
    sequence_name : str
        Sequence name.
    ceqstruct : SimpleNamespace
        PulCeq struct, based on github/HarmonizedMRI/PulCeq/src/pulCeq.h
    sys : _toppe.SystemSpecs
        TOPPE SystemSpecs object with GE scanner specifications.
    ignore_trigger : bool, optional
        If True, ignore all TTL pulses. The default is ``False``.
    sequence_path : str, optional
        Sequence files on the scanner. The default is
        ``"/usr/g/research/pulseq/v6/seq2ge/{sequence_name}"``.
    verbose : bool, optional
        Display info. The default is ``False`` (silent mode).

    """
    # Determine B1 scaling file by searching higher rf peak amongst parent blocks
    b1scaling_idx = _find_b1_scaling(ceqstruct)

    # Determine readout.mod as the last parent block containing ADC (to mimick ceq2ge.m)
    readout_idx = _find_readout(ceqstruct)

    # Loop over parent blocks and convert blocks to modules
    if verbose:
        print("Converting Pulseq blocks to TOPPE modules...", end="\t")
    modules = {"delay": None}  # dummy wait module
    for p in range(1, ceqstruct.n_parent_blocks):
        modules[f"module{p}.mod"] = _block2mod(
            p, ceqstruct.parent_blocks[p], sys, ceqstruct.sys.grad_raster_time
        )
    if verbose:
        print("done!\n")

    # Build core lut
    modnames = list(modules.keys())
    cores = ceqstruct.blocks_in_segment

    # Determine B1 scaling filename and readout filename
    b1scaling_name = modnames[b1scaling_idx]
    readout_name = modnames[readout_idx]

    # fix Loop
    ceqstruct.loop.modname = np.asarray(modnames)[ceqstruct.parent_blocks_idx].tolist()
    ceqstruct.loop.core = ceqstruct.segments_idx
    view = (ceqstruct.loop.adc_idx % sys.maxView) + 1
    sl = (ceqstruct.loop.adc_idx // sys.maxView) + 1
    assert (
        sl <= sys.maxSlice
    ).all(), f"max number of slices (={sys.maxSlice}) ecxeeded"
    echo = ceqstruct.loop.adc_idx // (sys.maxView * sys.maxSlice)
    assert (
        echo <= sys.maxEcho
    ).all(), f"max number of echoes (={sys.maxEcho}) ecxeeded"
    ceqstruct.loop.view = view.astype(int)
    ceqstruct.loop.slice = sl.astype(int)
    ceqstruct.loop.echo = echo.astype(int) + 1
    loop = _soa2aos(ceqstruct.n_max, ceqstruct.loop)

    # Build seqdict
    filesdict = {
        "sys": sys.__dict__,
        "modules": modules,
        "cores": cores,
        "loop": loop,
        "b1scaling_name": b1scaling_name,
        "readout_name": readout_name,
    }

    return filesdict


# %% local utils
def _find_b1_scaling(ceqstruct):
    peakb1 = np.zeros(ceqstruct.n_parent_blocks)
    for n in range(ceqstruct.n_parent_blocks):
        block = ceqstruct.parent_blocks[n]
        if block is not None and block.rf is not None:
            peakb1[n] = block.rf.amplitude
    b1scaling = np.argmax(peakb1)
    return b1scaling


def _find_readout(ceqstruct):
    readout = 0
    for n in range(ceqstruct.n_parent_blocks):
        block = ceqstruct.parent_blocks[n]
        if block is not None and block.adc is not None:
            readout = n
    return readout


def _block2mod(p, block, sys, dt):
    if block.rf is not None:
        assert block.adc is None, "A block can either have RF event or ADC, not both"
    if block.adc is not None:
        assert block.rf is None, "A block can either have RF event or ADC, not both"

    # initialize output module
    mod = {"ofname": f"module{p}.mod", "block_duration": block.block_duration}
    npre = 0
    rfres = None
    rf = []
    gx = []
    gy = []
    gz = []

    if block.rf is not None:
        rf, rfres, npre = _interp.rf2mod(p, block, sys)
        mod["rf"] = rf
    if block.gx is not None:
        gx, _ = _interp.grad2mod(p, block.gx, sys, dt)
        mod["gx"] = gx
    if block.gy is not None:
        gy, _ = _interp.grad2mod(p, block.gy, sys, dt)
        mod["gy"] = gy
    if block.gz is not None:
        gz, _ = _interp.grad2mod(p, block.gz, sys, dt)
        mod["gz"] = gz
    if block.adc is not None:
        rfres, npre = _interp.adc2mod(p, block, sys)
        mod["adc"] = True  # actual value is not important, code search for the key
    if hasattr(block, "trig"):
        mod["trig"] = {"delay": block.trig.delay}

    n = max(len(rf), len(gx), len(gy), len(gz))  # number of 4us samples in module
    if rfres is None:
        mod["nChop"] = (0, 0)
    else:
        mod["nChop"] = (
            npre,
            n - npre - rfres,
        )  # trim this many samples from beginning and end of RF/ADC window

    return mod


def _soa2aos(numel, input):
    output = []
    for n in range(numel):
        el = {
            "modname": input.modname[n],
            "Gamplitude": input.Gamplitude[n],
            "RFoffset": input.RFoffset[n],
            "RFphase": input.RFphase[n],
            "DAQphase": input.DAQphase[n],
            "trigout": input.trigout[n],
            "textra": input.textra[n],
            "rotmat": input.rotmat[n],
            "view": input.view[n],
            "slice": input.slice[n],
            "echo": input.echo[n],
            "core": input.core[n],
        }
        output.append(el)
    return output
