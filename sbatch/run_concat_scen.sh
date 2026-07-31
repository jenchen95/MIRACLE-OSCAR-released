#!/bin/bash

# Determine the script directory and project root
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(readlink -f "${SCRIPT_DIR}/..")

# Fixed parameters for concat_scen_results.py
NMC="2000"
OUTPUT_DIR="../data/data_output/AR6_drivers"
OVERRIDE="True"

# Build the command with fixed arguments
CMD="uv run concat_scen_results.py --nmc $NMC --output_dir \"$OUTPUT_DIR\" --override $OVERRIDE"

echo "Preparing to submit concat_scen_results.py job with command: $CMD"
echo "Submitting job to SLURM..."

# Submit job directly using a heredoc
sbatch << EOT
#!/bin/bash

#SBATCH --job-name=concat_scen
#SBATCH --output=concat_scen_%j.out
#SBATCH --error=concat_scen_%j.err
#SBATCH --time=2:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=256G
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=huangc@iiasa.ac.at

# Print some information about the job
echo "Running on host: \$(hostname)"
echo "Starting at: \$(date)"
echo "Directory: \$(pwd)"

# Use SLURM_SUBMIT_DIR to get the directory where the sbatch command was run
# and determine the project root from there
if [ -n "\$SLURM_SUBMIT_DIR" ]; then
    # We're running as a Slurm job
    SCRIPT_DIR="\$SLURM_SUBMIT_DIR"
    PROJECT_DIR="\$(readlink -f "\${SCRIPT_DIR}/..")"
else
    # We're running the script directly (not through Slurm)
    SCRIPT_DIR=\$(dirname "\$(readlink -f "\$0")")
    PROJECT_DIR=\$(readlink -f "\${SCRIPT_DIR}/..")
fi

echo "Script directory: \${SCRIPT_DIR}"
echo "Project directory: \${PROJECT_DIR}"

# Change to the project root directory
cd "\${PROJECT_DIR}"
echo "Changed to project root directory: \$(pwd)"

# Load necessary modules if available
if [ -f /opt/apps/lmod/8.7/init/bash ]; then
    source /opt/apps/lmod/8.7/init/bash
    module purge
    module load Python/3.12.3-GCCcore-13.3.0 2>/dev/null || echo "Module not available, skipping"
fi

# Check if uv is already installed
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
else
    echo "uv is already installed, skipping installation"
fi

# Add uv to PATH
export PATH="\$HOME/.cargo/bin:\$PATH"
export PATH="\$HOME/.local/bin:\$PATH"

# Verify pyproject.toml exists
if [ ! -f "\${PROJECT_DIR}/pyproject.toml" ]; then
    echo "ERROR: pyproject.toml not found in \${PROJECT_DIR}"
    echo "Current files in \${PROJECT_DIR}:"
    ls -la "\${PROJECT_DIR}"
    exit 1
fi

# Sync with uv.lock and use existing virtual environment
echo "Setting up Python environment with uv using pyproject.toml and uv.lock..."
uv sync

# Activate the virtual environment using absolute path
VENV_PATH="\${PROJECT_DIR}/.venv"
if [ -d "\${VENV_PATH}" ]; then
    echo "Activating virtual environment at \${VENV_PATH}"
    source "\${VENV_PATH}/bin/activate"
else
    echo "Creating virtual environment at \${VENV_PATH}"
    uv venv
    source "\${VENV_PATH}/bin/activate"
fi

# Set up any environment variables
export PYTHONUNBUFFERED=1

# Run the concat_scen_results.py script
echo "Running concat_scen_results.py..."
SRC_DIR="\${PROJECT_DIR}/src"
if [ -d "\${SRC_DIR}" ]; then
    cd "\${SRC_DIR}"
    echo "Changed to src directory: \$(pwd)"
    $CMD
else
    echo "ERROR: src directory not found at \${SRC_DIR}"
    exit 1
fi

# Print job completion information
echo "Job finished at: \$(date)"
EOT

echo "Job submitted successfully!" 