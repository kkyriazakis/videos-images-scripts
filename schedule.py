import runpy
import subprocess
import os
import sys
import lower_quality


def run_script(path, args=None):
    old_argv = sys.argv[:]
    try:
        sys.argv = [path] + (args or [])
        runpy.run_path(path, run_name="__main__")
    finally:
        sys.argv = old_argv


sample_jobs = [
    ("Lower-quality reencode (example)",        lambda: lower_quality.reencode(r"F:\\got_no_hdr\\S08E06.mkv", 90, r"F:\\got_no_hdr\\S08E06 The Iron Throne.mkv")),
    ("Strip subtitles batch",                   lambda: run_script(os.path.join("subtitles", "strip_subs_batch.py"))),
    ("Extract subtitles batch",                 lambda: run_script(os.path.join("subtitles", "extract_subs_batch.py"))),
    ("Re-encode folder (lower_quality_folder)", lambda: run_script(os.path.join("re_encode", "lower_quality_folder.py"))),
    ("Re-encode sample (lower_quality_sample)", lambda: run_script(os.path.join("re_encode", "lower_quality_sample.py"))),
    ("Remove HDR (PowerShell)",                 lambda: subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join("hdr", "remove_hdr.ps1")]))
]


if __name__ == "__main__":
    print("This is a schedule module.")

    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        idx = int(sys.argv[1])
        if 0 <= idx < len(sample_jobs):
            print("Running:", sample_jobs[idx][0])
            sample_jobs[idx][1]()
        else:
            print("Invalid job index")
    else:
        print("Available sample jobs:")
        for i, (name, _) in enumerate(sample_jobs):
            print(f"{i}: {name}")
        print("Run a job by passing its index, e.g. `python schedule.py 0`")
