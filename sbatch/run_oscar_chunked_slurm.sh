#!/bin/bash

# Default values
NMC="200"
RUN="both"
TOTAL_CHUNKS="10"
GROUP_BY="category"
MEM="64G"
CPUS="4"
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
    --chunks)
      TOTAL_CHUNKS="$2"
      shift 2
      ;;
    --group_by)
      GROUP_BY="$2"
      shift 2
      ;;
    --mem)
      MEM="$2"
      shift 2
      ;;
    --cpus)
      CPUS="$2"
      shift 2
      ;;
    --local)
      LOCAL_MODE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--nmc NUMBER] [--run TYPE] [--chunks NUMBER] [--group_by GROUP] [--mem MEMORY] [--cpus COUNT] [--local]"
      echo "  --nmc NUMBER: Set number of Monte Carlo simulations (default: 200)"
      echo "  --run TYPE: Set the run type (scen, cf, both) (default: both)"
      echo "  --chunks NUMBER: Set number of chunks to split MC samples (default: 10)"
      echo "  --group_by GROUP: How to group counterfactual scenarios (strategy, category) (default: strategy)"
      echo "  --mem MEMORY: Set memory per job (default: 64G, format: 64G, 128G, etc.)"
      echo "  --cpus COUNT: Set CPU cores per job (default: 4)"
      echo "  --local: Run the script locally instead of submitting to SLURM"
      exit 1
      ;;
  esac
done

# Determine the script directory and project root
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(readlink -f "${SCRIPT_DIR}/..")

# Function to run a single chunk
run_chunk() {
    local CHUNK_ID=$1
    
    # Print information about the job
    echo "Running chunk ${CHUNK_ID}/${TOTAL_CHUNKS} on host: $(hostname)"
    echo "Starting at: $(date)"
    echo "Directory: $(pwd)"
    
    # Change to the project root directory
    cd "${PROJECT_DIR}"
    
    # Load necessary modules if we're on a system that has them
    if [ -f /opt/apps/lmod/8.7/init/bash ]; then
        source /opt/apps/lmod/8.7/init/bash
        module purge
        #module load Python/3.12.3-GCCcore-13.3.0 2>/dev/null || echo "Module Python/3.12.3-GCCcore-13.3.0 not available, skipping"
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
    echo "Running OSCAR chunked scenario ${CHUNK_ID}/${TOTAL_CHUNKS}, grouping by ${GROUP_BY}..."
    SRC_DIR="${PROJECT_DIR}/src"
    if [ -d "${SRC_DIR}" ]; then
        cd "${SRC_DIR}"
        echo "Changed to src directory: $(pwd)"
        uv run run_scenarios_chunked.py --nmc ${NMC} --chunk_id ${CHUNK_ID} --total_chunks ${TOTAL_CHUNKS} \
                                       --group_by ${GROUP_BY} --run ${RUN}
    else
        echo "ERROR: src directory not found at ${SRC_DIR}"
        exit 1
    fi
    
    # Print job completion information
    echo "Chunk ${CHUNK_ID}/${TOTAL_CHUNKS} finished at: $(date)"
}

if [ "$LOCAL_MODE" = true ]; then
    echo "Running all chunks locally in sequence..."
    for ((i=1; i<=${TOTAL_CHUNKS}; i++)); do
        echo "Starting chunk ${i}/${TOTAL_CHUNKS}..."
        run_chunk $i
    done
    echo "All local executions completed!"
else
    echo "Preparing to submit OSCAR chunked jobs..."
    echo "Total chunks: ${TOTAL_CHUNKS}"
    echo "Monte Carlo samples: ${NMC}"
    echo "Run type: ${RUN}"
    echo "Group by: ${GROUP_BY}"
    echo "Memory per job: ${MEM}"
    echo "CPUs per job: ${CPUS}"
    
    # Submit job array
    sbatch << EOT
#!/bin/bash

#SBATCH --job-name=oscar_chunks
#SBATCH --output=oscar_chunk_%A_%a.out
#SBATCH --error=oscar_chunk_%A_%a.err
#SBATCH --time=24:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=${CPUS}
#SBATCH --mem=${MEM}
#SBATCH --array=1-${TOTAL_CHUNKS}
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=huangc@iiasa.ac.at

# Print some information about the job
echo "Running on host: \$(hostname)"
echo "Starting at: \$(date)"
echo "SLURM_ARRAY_TASK_ID: \${SLURM_ARRAY_TASK_ID}"
echo "Directory: \$(pwd)"
echo "CPUs: ${CPUS}, Memory: ${MEM}"

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
# module load Python/3.12.3-GCCcore-13.3.0

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
uv venv
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

# Run the OSCAR scenarios for this chunk
echo "Running OSCAR scenarios for chunk \${SLURM_ARRAY_TASK_ID}/${TOTAL_CHUNKS}, grouping by ${GROUP_BY}..."
SRC_DIR="\${PROJECT_DIR}/src"
if [ -d "\${SRC_DIR}" ]; then
    cd "\${SRC_DIR}"
    echo "Changed to src directory: \$(pwd)"
    uv run run_scenarios_chunked.py --nmc ${NMC} --chunk_id \${SLURM_ARRAY_TASK_ID} --total_chunks ${TOTAL_CHUNKS} \
                                   --group_by ${GROUP_BY} --run ${RUN}
else
    echo "ERROR: src directory not found at \${SRC_DIR}"
    exit 1
fi

# Print job completion information
echo "Job finished at: \$(date)"
EOT

    echo "Job array submitted successfully!"
fi 