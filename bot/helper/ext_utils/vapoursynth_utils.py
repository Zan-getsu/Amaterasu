import asyncio
import subprocess
from pathlib import Path
from bot import LOGGER

def generate_vpy_script(input_file: str, output_vpy: str) -> str:
    """
    Dynamically generates the VapourSynth script for the anime preprocessing pipeline.
    Uses dfttest, BM3D, NLM, MVTools, and dehalo_alpha.
    """
    input_file = str(Path(input_file).absolute())
    # Ensure forward slashes for cross-platform safety in the VapourSynth script
    input_file_escaped = input_file.replace('\\', '/')
    
    script_content = f"""import vapoursynth as vs
from vsdenoise import DFTTest, BM3D, NLM, MVTools
from vsdehalo import dehalo_alpha

core = vs.core
# Load video using LWLibavSource (preferred for indexing) or FFMS2
try:
    clip = core.lsmas.LWLibavSource(r"{input_file_escaped}")
except Exception:
    clip = core.ffms2.Source(r"{input_file_escaped}")

# Denoise (dfttest) with sigma curve
sigma_curve = {{0.0: 0.3, 0.4: 0.3, 0.6: 0.6, 0.8: 1.5, 1.0: 2.0}}
clip = DFTTest.denoise(clip, sloc=sigma_curve, tr=2, planes=[0, 1, 2])

# BM3D Denoise on luma
clip = BM3D.denoise(clip, sigma=32, tr=2, profile=BM3D.Profile.FAST, planes=0)

# Non-Local Means (NLM) on chroma
clip = NLM.denoise(clip, h=0.6, tr=2, a=2, planes=[1, 2])

# Motion-Compensated Degrain
clip = MVTools.denoise(clip, thSAD=100, prefilter=MVTools.Prefilter.DFTTEST, preset=MVTools.Preset.HQ_SAD)

# Dehalo
clip = dehalo_alpha(clip)

# Set 10-bit output and pass frames for SVT-AV1
clip = core.resize.Point(clip, format=vs.YUV420P10)
clip.set_output()
"""
    with open(output_vpy, 'w', encoding='utf-8') as f:
        f.write(script_content)
    
    return output_vpy

async def run_vspipe_ffmpeg(input_file: str, ffmpeg_cmd: list) -> tuple[bool, str]:
    """
    Executes vspipe and pipes stdout to ffmpeg stdin asynchronously.
    """
    vpy_script = str(Path(input_file).with_suffix('.vpy'))
    generate_vpy_script(input_file, vpy_script)
    
    vspipe_cmd = ["vspipe", "--y4m", vpy_script, "-"]
    
    LOGGER.info(f"Running VapourSynth Pipeline for: {input_file}")
    LOGGER.info(f"VSPipe Command: {' '.join(vspipe_cmd)}")
    LOGGER.info(f"FFmpeg Command: {' '.join(ffmpeg_cmd)}")
    
    try:
        vspipe_proc = await asyncio.create_subprocess_exec(
            *vspipe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        ffmpeg_proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdin=vspipe_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Close stdout so vspipe receives SIGPIPE if ffmpeg exits early
        if vspipe_proc.stdout:
            vspipe_proc.stdout.close()
            
        stdout, stderr = await ffmpeg_proc.communicate()
        
        if ffmpeg_proc.returncode != 0:
            error_msg = stderr.decode('utf-8') if stderr else "Unknown FFmpeg Error"
            vspipe_err = (await vspipe_proc.stderr.read()).decode('utf-8') if vspipe_proc.stderr else ""
            LOGGER.error(f"FFmpeg Error in VSPipe Pipeline: {error_msg}\nVSPipe Error: {vspipe_err}")
            return False, error_msg
            
        return True, ""
        
    except Exception as e:
        LOGGER.error(f"Failed to run VSPipe/FFmpeg pipeline: {e}")
        return False, str(e)
