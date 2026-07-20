Here is a proposed design to add the `--git-pull` option to the benchmark script:

### Proposed Design

**1. CLI Interface Update**
We will add an optional `--git-pull` flag to the `run-benchmark` command in the `sweperf` script. 

Example usage:
```bash
./sweperf run-benchmark --git-pull 3600 50
```
OR
```bash
./sweperf run-benchmark 3600 50
```

**2. Argument Parsing**
We will update the argument checks within the `run-benchmark)` case block. If the first argument is `--git-pull`, we'll set a `DO_GIT_PULL` flag to `true` and `shift` the arguments. We'll then do the standard validation checking that exactly 2 arguments (`DURATION` and `CONCURRENCY`) remain.

**3. Git Pull Execution**
Right before launching the background watchers (`python3 benchmark/*.py`) and the submitter loop, we will add:
```bash
if [ "$DO_GIT_PULL" = true ]; then
    echo "Pulling latest changes from source repo..."
    git -C "$(dirname "$0")" pull
fi
```
Using `git -C "$(dirname "$0")" pull` ensures that it reliably pulls the `sweperf` repository regardless of which working directory the user initiated the script from.

**4. Safety**
Modifying a bash script while it's running can sometimes cause errors if the script parser reads from the modified file. However, because the entire `run-benchmark` command sits inside a `case` block that runs until the end of the script, Bash loads the entire command block into memory before execution. This means running `git pull` on the executing file itself is perfectly safe. Furthermore, any separate companion scripts (like `node_watcher.py` or `submitter.sh`) will be loaded *after* the pull finishes, guaranteeing they run using the most up-to-date versions from the remote repository.

Does this align with what you're looking for, or did you mean doing a `git pull` for a target experimental repository / within the testing pods themselves?
