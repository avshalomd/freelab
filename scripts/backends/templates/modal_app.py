"""freelab Modal app (copied from freelab's scripts/backends/templates/modal_app.py; see
skills/compute/references/modal.md): runs EXP/train.py on a GPU, detached, with its outputs on the private Volume
freelab-runs (committed every minute, so they can be watched). Nothing to fill in: the experiment directory and
runlib.py come from the FREELAB_EXP and FREELAB_RUNLIB environment variables at launch."""
import os, shlex, subprocess, sys
import modal

EXP, RUNLIB = os.environ.get("FREELAB_EXP", ""), os.environ.get("FREELAB_RUNLIB", "")
image = modal.Image.debian_slim(python_version="3.12")
if EXP and modal.is_local():  # built on the laptop only; the container resolves the function without it
    image = (image.pip_install_from_requirements(f"{EXP}/requirements.txt")
             .add_local_dir(EXP, "/exp", ignore=["**/__pycache__", "**/lab", "**/.venv", "**/.env*", "**/.git", "runlib.py"])
             .add_local_file(RUNLIB, "/exp/runlib.py"))
app = modal.App("freelab")
vol = modal.Volume.from_name("freelab-runs", create_if_missing=True)


@app.function(image=image, volumes={"/runs": vol}, timeout=30 * 60)
def run(run_id: str, minutes: float, args: list[str]) -> int:
    sys.path.insert(0, "/exp")
    from runlib import has_checkpoint
    cmd = ["python", "-u", "/exp/train.py", "--out", f"/runs/{run_id}", "--max-minutes", f"{minutes:g}", *args]
    if has_checkpoint(f"/runs/{run_id}/ckpt"):  # a restart after preemption, or a moved-in checkpoint
        cmd.append("--resume")
    proc = subprocess.Popen(cmd, cwd="/exp")
    try:
        while True:
            try:
                return proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                try:
                    vol.commit()
                except Exception as e:  # a missed commit must not end the run
                    print(f"freelab: volume commit failed ({e})", flush=True)
    finally:
        if proc.poll() is None:  # preempted or stopped: let runlib checkpoint first
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        vol.commit()


@app.local_entrypoint()
def main(run_id: str, gpu: str = "T4", minutes: float = 30, args: str = ""):
    call = run.with_options(gpu=gpu, timeout=int((minutes + 10) * 60)).spawn(run_id, minutes, shlex.split(args))
    print(f"started {run_id} on a {gpu}, up to {minutes:g} min; function call {call.object_id}")
