# Running OSCAR on Slurm or Locally

This document provides instructions for running the OSCAR model on both a Slurm-based non-interactive computing service and locally on your machine.

## Prerequisites

- Access to the non-interactive computing service (https://jupyter.iiasa.ac.at) for SLURM mode
- Your OSCAR project files uploaded to the cluster (for SLURM mode) or on your local machine

## Setup

1. For SLURM mode: Log in to JupyterHub via https://jupyter.iiasa.ac.at and choose the non-interactive option

2. Upload your OSCAR project files:
   - For SLURM mode: Upload to your home directory or project directory on the cluster
     - You can use the JupyterHub interface to upload files
     - Or use `scp` or `rsync` to transfer files from your local machine
   - For local mode: Keep files on your local machine

3. Make sure the data directory structure is correct:
   ```
   data/
   ├── data_raw/
   │   └── AR6_drivers/
   │       ├── Par_<nmc>mc.nc
   │       ├── Ini_<nmc>mc.nc
   │       ├── For_hist_origin_<nmc>mc.nc
   │       ├── Out_hist_<nmc>mc.nc
   │       ├── For_scen_AR6_<nmc>mc.nc
   │       └── r10_ghg.parquet
   │       └── emissions_ar6.nc
   │       └── r10_co2_add.parquet
   ├── data_man/
   │   └── category.csv
   └── data_output/
       └── AR6_drivers/
           └── chunks/
   │           ├── Out_scen_<nmc>mc_<chunk>of<chunks>.nc
   │       ├── Out_scen_<nmc>mc.nc
   │       ├── Out_scen_cf_<nmc>mc_category_<category>_<chunk>of<chunks>.nc
   │       ├── weight_<drivers>_<nmc>mc.nc
   │       ├── dtg_weighted_hist_<nmc>mc.parquet
   │       ├── dtg_weighted_scen_<nmc>mc.parquet
   │       ├── dtg_weighted_scen_<nmc>mc_category_all.parquet
   │       ├── dtg_weighted_cf_<nmc>mc_category_<category>_strategy_<strategy>.parquet
   ```

## Package Management with uv

The job scripts use `uv` instead of `pip` for package installation. `uv` is a faster alternative to `pip` that can significantly speed up your environment setup.

### Using pyproject.toml and uv.lock

The scripts are configured to use the existing `pyproject.toml` and `uv.lock` files in your project. This approach has several advantages:

1. **Faster installation**: `uv sync` is much faster than installing packages from scratch
2. **Reproducible environments**: The exact same package versions will be installed every time
3. **Dependency resolution**: All dependencies are already resolved in the lock file

The scripts will:
1. Install `uv` using the official installer (if not already installed)
2. Create a virtual environment using `uv venv` (if it doesn't exist)
3. Sync dependencies from the lock file using `uv sync`
4. Run your script using `uv run` instead of `python` directly

If you need to update dependencies:
1. Make changes to your `pyproject.toml` file
2. Run `uv pip compile pyproject.toml -o uv.lock` locally to update the lock file
3. Upload the updated lock file to the cluster

## Running Options

OSCAR can be run in several ways:

1. **Standard Mode** - Process all Monte Carlo samples at once (`run_oscar_slurm.sh`)
2. **Chunked Mode** - Split Monte Carlo samples into chunks for parallel processing (`run_oscar_chunked_slurm.sh`)
3. **Local Mode** - Run directly on your machine instead of submitting to SLURM (available for both modes)

Each script automatically detects if SLURM is available. If not, it defaults to local mode.

## Standard Mode: Running All MC Samples at Once

This mode processes all Monte Carlo samples in a single job.

### Basic Usage

```bash
# Run with default settings (auto-detects local/SLURM mode)
./sbatch/run_oscar_slurm.sh

# Run with specific number of Monte Carlo simulations
./sbatch/run_oscar_slurm.sh --nmc 20

# Run with specific run type
./sbatch/run_oscar_slurm.sh --run cf

# Run with both parameters
./sbatch/run_oscar_slurm.sh --nmc 50 --run both

# Force local execution even on a SLURM system
./sbatch/run_oscar_slurm.sh --local --nmc 20 --run cf
```

### Command-Line Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--nmc NUMBER` | Set the number of Monte Carlo simulations | `--nmc 50` |
| `--run TYPE` | Set the run type (options: scen, cf, both) | `--run cf` |
| `--local` | Force local execution (don't submit to SLURM) | `--local` |

## Chunked Mode: Parallel Processing of MC Samples

This mode divides Monte Carlo samples into chunks for parallel processing, which is useful for:
- Avoiding memory limitations
- Reducing the time needed for each job
- Improving resource utilization

### Basic Usage

```bash
# Run with default settings (10 chunks of 200 MC samples)
./sbatch/run_oscar_chunked_slurm.sh

# Run 200 MC samples split into 20 chunks
./sbatch/run_oscar_chunked_slurm.sh --nmc 200 --chunks 20

# Run just counterfactual scenarios with custom resources
./sbatch/run_oscar_chunked_slurm.sh --run cf --mem 96G --cpus 6

# Process large runs with many chunks and custom resources
./sbatch/run_oscar_chunked_slurm.sh --nmc 1000 --chunks 50 --mem 128G --cpus 8

# Run locally for testing
./sbatch/run_oscar_chunked_slurm.sh --nmc 50 --chunks 5 --local
```

### Command-Line Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--nmc NUMBER` | Total number of Monte Carlo simulations | `--nmc 200` |
| `--chunks NUMBER` | Number of chunks to split MC samples | `--chunks 10` |
| `--run TYPE` | Set the run type (options: scen, cf, both) | `--run cf` |
| `--mem MEMORY` | Memory per job (format: 64G, 128G, etc.) | `--mem 128G` |
| `--cpus COUNT` | CPU cores per job | `--cpus 8` |
| `--local` | Force local execution | `--local` |

### Chunking Strategy Recommendations

- **For large MC samples** (200+):
  - Use more chunks (10-50)
  - Allocate less memory per chunk (32G-64G)
  
- **For memory-intensive runs**:
  - Increase the number of chunks
  - Or increase memory per chunk (96G-256G)
  
- **For faster processing**:
  - Increase CPUs per chunk if your code benefits from parallelism
  - Distribute across more chunks for better resource utilization

- **Output files**: Results are saved with chunk identifiers (e.g., `Out_scen_200mc_1of10.nc`)

## Monitoring and Output

1. Monitor SLURM job status:
   ```bash
   squeue -u $USER
   ```

2. Check the output files:
   - Standard mode output: `oscar_scenarios_<jobid>.out`
   - Chunked mode output: `oscar_chunk_<jobid>_<chunk_id>.out`
   - Standard mode errors: `oscar_scenarios_<jobid>.err`
   - Chunked mode errors: `oscar_chunk_<jobid>_<chunk_id>.err`
   - Results for standard mode: `data/data_output/AR6_drivers/Out_scen_<nmc>mc.nc`
   - Results for chunked mode: `data/data_output/AR6_drivers/chunks/Out_scen_<nmc>mc_<chunk>of<total>.nc`

## Troubleshooting

- If jobs fail due to memory issues:
  - For standard mode: Increase memory in script or switch to chunked mode
  - For chunked mode: Increase the number of chunks or increase memory per chunk
  
- For time limit issues:
  - Increase the time limit in the script
  - Or use more chunks with less workload per chunk
  
- Check error files for specific error messages
  - Look for "MemoryError" or "Killed" in Python output
  - Check SLURM errors like "CANCELLED" or "OUT OF MEMORY"

## Advanced Usage

For more complex job requirements:

- Edit the SLURM directives in the script
- Adjust Python environment setup
- Add additional command-line parameters

## Running AR6 Drivers

In addition to the main scenarios runner, there's a specialized script for generating AR6 drivers data: `get_drivers_slurm.sh`. This script is specifically designed to run the `get_AR6_drivers.py` script, which prepares necessary driver data for the OSCAR model.

### Basic Usage

```bash
# Run with default settings (auto-detects local/SLURM mode)
./sbatch/get_drivers_slurm.sh

# Run with specific number of Monte Carlo simulations
./sbatch/get_drivers_slurm.sh --nmc 500

# Generate historical data 
./sbatch/get_drivers_slurm.sh --reload_hist

# Generate all data with 1000 MC simulations
./sbatch/get_drivers_slurm.sh --nmc 1000 --reload_hist --reload_scen --reload_ar6 --scen_update

# Force local execution even on a SLURM system
./sbatch/get_drivers_slurm.sh --local --reload_ar6
```

### Command-Line Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--nmc NUMBER` | Set the number of Monte Carlo simulations | `--nmc 500` |
| `--reload_hist` | Reload the calculation of historical data | `--reload_hist` |
| `--reload_scen` | Reload For_scen data | `--reload_scen` |
| `--reload_ar6` | Reload AR6 emission data | `--reload_ar6` |
| `--scen_update` | Update For_scen data with emission series | `--scen_update` |
| `--local` | Force local execution (don't submit to SLURM) | `--local` |

Note that when `--reload_hist` is enabled, the script will automatically enable `--reload_scen` and `--scen_update` as they depend on the historical data.

### Expected Outputs

The script will generate various data files in the `data/data_raw/AR6_drivers/` directory:

- `Par_<nmc>mc.nc` - Parameter datasets
- `Ini_<nmc>mc.nc` - Initial condition datasets
- `For_hist_origin_<nmc>mc.nc` - Historical forcing data
- `For_scen_SSP_<nmc>mc.nc` - SSP scenario forcing data
- `emissions_ar6.nc` - AR6 emissions data
- `For_scen_AR6_<nmc>mc.nc` - AR6 scenario forcing data

These files are required inputs for running OSCAR model scenarios.

