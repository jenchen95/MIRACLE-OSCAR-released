#!/bin/bash

# Default values
NMC=200
RELOAD_HIST=false
RELOAD_SCEN=false
RELOAD_AR6=false
SCEN_UPDATE=false
LOCAL_MODE=false
HIST_DRIVER="edrive"

# Check if sbatch command is available
if ! command -v sbatch &> /dev/null; then
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
    --reload_hist)
      RELOAD_HIST=true
      shift
      ;;
    --reload_scen)
      RELOAD_SCEN=true
      shift
      ;;
    --reload_ar6)
      RELOAD_AR6=true
      shift
      ;;
    --scen_update)
      SCEN_UPDATE=true
      shift
      ;;
    --hist_driver)
      HIST_DRIVER="$2"
      shift 2
      ;;
    --local)
      LOCAL_MODE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--nmc NUMBER] [--reload_hist] [--reload_scen] [--reload_ar6] [--scen_update] [--hist_driver cdrive|edrive] [--local]"
      echo "  --nmc NUMBER: Set number of Monte Carlo simulations (default: 200)"
      echo "  --reload_hist: Reload the calculation of historical data"
      echo "  --reload_scen: Reload For_scen data"
      echo "  --reload_ar6: Reload AR6 emission data"
      echo "  --scen_update: Update For_scen data with emission series"
      echo "  --hist_driver: Choose which historical driver to use: concentration-based or emission-based (default: cdrive)"
      echo "  --local: Run the script locally instead of submitting to SLURM"
      exit 1
      ;;
  esac
done

# Build the command with arguments
CMD="uv run get_AR6_drivers.py --nmc $NMC --hist_driver $HIST_DRIVER"
if [ "$RELOAD_HIST" = true ]; then CMD="$CMD --reload_hist"; fi
if [ "$RELOAD_SCEN" = true ]; then CMD="$CMD --reload_scen"; fi
if [ "$RELOAD_AR6" = true ]; then CMD="$CMD --reload_ar6"; fi
if [ "$SCEN_UPDATE" = true ]; then CMD="$CMD --scen_update"; fi

# Get script directory and project root
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(readlink -f "${SCRIPT_DIR}/..")

# Function to run the actual commands
run_commands() {
    echo "Running on host: $(hostname)"
    echo "Starting at: $(date)"
    
    # Change to the project root directory
    cd "${PROJECT_DIR}/src"
    echo "Working directory: $(pwd)"
    
    # Load necessary modules if available
    if [ -f /opt/apps/lmod/8.7/init/bash ]; then
        source /opt/apps/lmod/8.7/init/bash
        module purge
        module load Python/3.12.3-GCCcore-13.3.0 2>/dev/null || echo "Module Python/3.12.3-GCCcore-13.3.0 not available"
    fi
    
    # Setup Python environment using uv
    if ! command -v uv &> /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
        export PATH="$HOME/.local/bin:$PATH"
    fi
    
    # Activate virtual environment
    if [ -d "${PROJECT_DIR}/.venv" ]; then
        source "${PROJECT_DIR}/.venv/bin/activate"
    else
        cd "${PROJECT_DIR}"
        uv venv
        uv sync
        source "${PROJECT_DIR}/.venv/bin/activate"
        cd "${PROJECT_DIR}/src"
    fi
    
    # Run the command
    echo "Running command: $CMD"
    eval $CMD
    
    echo "Job finished at: $(date)"
}

if [ "$LOCAL_MODE" = true ]; then
    echo "Running locally with command: $CMD"
    run_commands
else
    echo "Submitting job to SLURM with command: $CMD"
    
    sbatch << EOT
#!/bin/bash
#SBATCH --job-name=oscar_drivers
#SBATCH --output=oscar_drivers_%j.out
#SBATCH --error=oscar_drivers_%j.err
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=huangc@iiasa.ac.at

SCRIPT_DIR="\$SLURM_SUBMIT_DIR"
PROJECT_DIR="\$(readlink -f "\${SCRIPT_DIR}/..")"

# Load modules
source /opt/apps/lmod/8.7/init/bash
module purge
module load Python/3.12.3-GCCcore-13.3.0

# Setup Python environment
cd "\${PROJECT_DIR}"
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="\$HOME/.cargo/bin:\$PATH"
    export PATH="\$HOME/.local/bin:\$PATH"
fi

# Activate or create virtual environment
if [ -d "\${PROJECT_DIR}/.venv" ]; then
    source "\${PROJECT_DIR}/.venv/bin/activate"
else
    uv venv
    uv sync
    source "\${PROJECT_DIR}/.venv/bin/activate"
fi

# Run the command
cd "\${PROJECT_DIR}/src"
echo "Running command: $CMD"
echo "Starting at: \$(date)"
$CMD
echo "Finished at: \$(date)"
EOT

    echo "Job submitted successfully!"
fi
