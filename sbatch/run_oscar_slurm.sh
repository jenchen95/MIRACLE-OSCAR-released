#!/bin/bash

# Default values
NMC=""
RUN=""
LOCAL_MODE=false

# Check if sbatch command is available
if ! command -v sbatch &> /dev/null; then
    # sbatch not found, assume local mode by default
    LOCAL_MODE=true
    echo "SLURM (sbatch) not detected - defaulting to local execution mode"
fi

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --nmc)
      NMC="$2"
      shift 2
      ;;
    --run)
      RUN="$2"
      shift 2
      ;;
    --local)
      LOCAL_MODE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--nmc NUMBER] [--run TYPE] [--local]"
      echo "  --nmc NUMBER: Set number of Monte Carlo simulations"
      echo "  --run TYPE: Set the run type (e.g., cf, hist)"
      echo "  --local: Run the script locally instead of submitting to SLURM"
      exit 1
      ;;
  esac
done

# Build the command with arguments if provided
CMD="uv run run_scenarios.py"
if [ -n "$NMC" ]; then
  CMD="$CMD --nmc $NMC"
fi
if [ -n "$RUN" ]; then
  CMD="$CMD --run $RUN"
fi

# Determine the script directory and project root
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(readlink -f "${SCRIPT_DIR}/..")

# Function to run the actual commands
run_oscar_commands() {
    # Print information about the job
    echo "Running on host: $(hostname)"
    echo "Starting at: $(date)"
    echo "Directory: $(pwd)"
    
    echo "Script directory: ${SCRIPT_DIR}"
    echo "Project directory: ${PROJECT_DIR}"
    
    # Change to the project root directory
    cd "${PROJECT_DIR}"
    echo "Changed to project root directory: $(pwd)"
    
    # Load necessary modules if we're on a system that has them
    if [ -f /opt/apps/lmod/8.7/init/bash ]; then
        source /opt/apps/lmod/8.7/init/bash
        module purge
        module load Python/3.12.3-GCCcore-13.3.0 2>/dev/null || echo "Module Python/3.12.3-GCCcore-13.3.0 not available, skipping"
    else
        echo "Module system not detected, skipping module loads"
    fi
    
    # Check if uv is already installed
    if ! command -v uv &> /dev/null; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        echo "uv is already installed, skipping installation"
    fi
    
    # Add uv to PATH
    export PATH="$HOME/.cargo/bin:$PATH"
    export PATH="$HOME/.local/bin:$PATH"
    
    # Verify pyproject.toml exists
    if [ ! -f "${PROJECT_DIR}/pyproject.toml" ]; then
        echo "ERROR: pyproject.toml not found in ${PROJECT_DIR}"
        echo "Current files in ${PROJECT_DIR}:"
        ls -la "${PROJECT_DIR}"
        echo "Current files in ${SCRIPT_DIR}:"
        ls -la "${SCRIPT_DIR}"
        exit 1
    fi
    
    # Sync with uv.lock and use existing virtual environment
    echo "Setting up Python environment with uv using pyproject.toml and uv.lock..."
    uv sync
    
    # Activate the virtual environment using absolute path
    VENV_PATH="${PROJECT_DIR}/.venv"
    if [ -d "${VENV_PATH}" ]; then
        echo "Activating virtual environment at ${VENV_PATH}"
        source "${VENV_PATH}/bin/activate"
    else
        echo "Creating virtual environment at ${VENV_PATH}"
        uv venv
        source "${VENV_PATH}/bin/activate"
    fi
    
    # Set up any environment variables
    export PYTHONUNBUFFERED=1
    
    # Run the OSCAR scenarios
    echo "Running OSCAR scenarios..."
    SRC_DIR="${PROJECT_DIR}/src"
    if [ -d "${SRC_DIR}" ]; then
        cd "${SRC_DIR}"
        echo "Changed to src directory: $(pwd)"
        eval $CMD
    else
        echo "ERROR: src directory not found at ${SRC_DIR}"
        exit 1
    fi
    
    # Print job completion information
    echo "Job finished at: $(date)"
}

if [ "$LOCAL_MODE" = true ]; then
    echo "Running OSCAR locally with command: $CMD"
    run_oscar_commands
    echo "Local execution completed!"
else
    echo "Preparing to submit OSCAR job with command: $CMD"
    echo "Submitting job to SLURM..."
    
    # Submit job directly using a heredoc
    sbatch << EOT
#!/bin/bash

#SBATCH --job-name=oscar_scenarios
#SBATCH --output=oscar_scenarios_%j.out
#SBATCH --error=oscar_scenarios_%j.err
#SBATCH --time=10:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
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

# Load necessary modules
source /opt/apps/lmod/8.7/init/bash
module purge
module load Python/3.12.3-GCCcore-13.3.0

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
    echo "Current files in \${SCRIPT_DIR}:"
    ls -la "\${SCRIPT_DIR}"
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

# Run the OSCAR scenarios
echo "Running OSCAR scenarios..."
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
fi 