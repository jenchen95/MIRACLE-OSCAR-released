import os
import xarray as xr
import polars as pl
from AR6_func import run_oscar_with_emissions
import gc
import argparse
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--nmc", help="Total number of MC samples", type=int, default=200)
parser.add_argument("--chunk_id", help="Chunk ID (1-based)", type=int, required=True)
parser.add_argument("--total_chunks", help="Total number of chunks", type=int, required=True)
parser.add_argument("--run", help="Choose which scenarios to run: 'scen', 'cf', or 'both'", 
                    type=str, choices=['scen', 'cf', 'both'], default='both')
parser.add_argument("--group_by", help="Group counterfactual scenarios by 'strategy' or 'category'", 
                    type=str, choices=['strategy', 'category'], default='category')
args = parser.parse_args()

# Calculate which MC samples this chunk should process
samples_per_chunk = (args.nmc + args.total_chunks - 1) // args.total_chunks  # Ceiling division
start_idx = (args.chunk_id - 1) * samples_per_chunk
end_idx = min(start_idx + samples_per_chunk, args.nmc)

print(f"Processing chunk {args.chunk_id}/{args.total_chunks}: MC samples {start_idx} to {end_idx-1} (of {args.nmc} total)")
print(f"Chunk range: {start_idx}-{end_idx-1}")
print(f"Group by: {args.group_by}")

# Load just this chunk of samples
print(f"Loading data for chunk {args.chunk_id}...")
Par = xr.open_dataset(f'../data/data_raw/AR6_drivers/Par_{args.nmc}mc.nc').isel(config=slice(start_idx, end_idx))
Ini = xr.open_dataset(f'../data/data_raw/AR6_drivers/Ini_{args.nmc}mc.nc').isel(config=slice(start_idx, end_idx))
For_scen = xr.open_dataset(f'../data/data_raw/AR6_drivers/For_scen_AR6_{args.nmc}mc.nc')
category = pl.read_csv('../data/data_man/category.csv')

print(f"Loaded data for chunk {args.chunk_id}. Preparing scenario data...")

# The rest of the processing follows the original script
ar6_cf_add = (
    pl.read_parquet('../data/data_raw/AR6_drivers/r10_co2_add.parquet')
    .join(category, on=['model', 'scenario'], how='left')
    .select(pl.col('model', 'scenario', 'category', 'strategy', 'year', 'Emissions'))
    .with_columns(
        scen = pl.col('model') + '|' + pl.col('scenario'),
        year=pl.col('year').cast(pl.Int64),
        Emissions = pl.col('Emissions') * (1.0/1000.0) * (12.0/44.0))  # From Mt CO2 to PgC
)

For_scen = For_scen.sel(scen = ar6_cf_add['scen'].unique().to_numpy())

# Create a copy of For_scen for the counterfactual scenario
strategies = ar6_cf_add['strategy'].unique().to_numpy()

# Only create the counterfactual scenario if needed
if args.run in ['cf', 'both']:
    print("Preparing counterfactual scenario data...")
    For_scen_cf = For_scen.copy(deep=True).expand_dims(strategy=strategies)
    
    # Convert ar6_cf to xarray format matching For_scen dimensions
    ar6_cf_add_xr = ar6_cf_add.to_pandas().set_index(['strategy', 'scen', 'year'])['Emissions'].to_xarray()
    
    # Create a new dataset with the updated Eff values
    # First, get the indices where we want to update
    indices = dict(reg_land=0, 
                   year=ar6_cf_add_xr.coords['year'].values, 
                   scen=ar6_cf_add_xr.coords['scen'].values, 
                   strategy=ar6_cf_add_xr.coords['strategy'].values)
    
    # Create a copy of the Eff variable
    new_eff = For_scen_cf['Eff'].copy(deep=True)
    
    # Update the values at the specified indices
    new_eff.loc[indices] = ar6_cf_add_xr
    
    # Assign the updated variable back to the dataset
    For_scen_cf['Eff'] = new_eff
    
    # Create a new dimension with concatenated values
    # First, create a list to hold our datasets
    datasets = []
    
    # Loop through each strategy
    for strat in For_scen_cf.strategy.values:
        # Extract the dataset for this strategy
        ds = For_scen_cf.sel(strategy=strat)
        
        # Check if 'strategy' is still a dimension
        if 'strategy' in ds.dims:
            ds = ds.squeeze('strategy')
        
        # Create new scen values by concatenating scen and strategy
        new_scen_values = [f"{s}|{strat}" for s in ds.scen.values]
        
        # Assign these as a new coordinate
        ds = ds.assign_coords(new_scen=('scen', new_scen_values))
        
        # Swap dimensions and drop the old one
        ds = ds.swap_dims({'scen': 'new_scen'})
        ds = ds.rename({'scen': 'scen_ori'})
        ds = ds.rename({'new_scen': 'scen'})
        
        # Add to our list
        datasets.append(ds)
    
    # Concatenate all datasets along the scen dimension
    For_scen_cf = xr.concat(datasets, dim='scen')
    print("Counterfactual scenario data prepared.")

# Create output folder structure
export_folder = '../data/data_output/AR6_drivers/chunks'
if not os.path.exists(export_folder):
    os.makedirs(export_folder)

# Define output file paths with chunk information
chunk_suffix = f"_{args.chunk_id}of{args.total_chunks}"
scen_output_file = f'{export_folder}/Out_scen_{args.nmc}mc{chunk_suffix}.nc'
cf_output_file = f'{export_folder}/Out_scen_cf_{args.nmc}mc{chunk_suffix}.nc'

# Function to check if a file is locked/in use
def is_file_in_use(filepath):
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, 'a'):
            pass
        return False
    except IOError:
        return True

# Add timestamp if file is in use
def get_safe_filepath(filepath):
    if is_file_in_use(filepath):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base, ext = os.path.splitext(filepath)
        new_filepath = f"{base}_{timestamp}{ext}"
        print(f"File {filepath} is in use. Saving to alternative path: {new_filepath}")
        return new_filepath
    else:
        print(f"File {filepath} is not in use. Saving to original path.")
        return filepath

# Run scenarios based on the --run argument
if args.run in ['scen', 'both']:
    print(f"Running standard scenario with Monte Carlo samples {start_idx}-{end_idx-1}...")
    safe_scen_output_file = get_safe_filepath(scen_output_file)
    out = run_oscar_with_emissions(Par, Ini, For_scen)
    out.to_netcdf(safe_scen_output_file)
    print(f"Standard scenario results saved to {safe_scen_output_file}")
    del out
    gc.collect()

if args.run in ['cf', 'both']:
    print(f"Running counterfactual scenario with Monte Carlo samples {start_idx}-{end_idx-1}...")
    
    # Get the list of groups based on the group_by parameter
    if args.group_by == 'strategy':
        # Verify strategy is a coordinate and get unique values
        if 'strategy' not in For_scen_cf.coords:
            raise ValueError(f"'strategy' coordinate not found in For_scen_cf. Cannot group by strategy.")
        
        groups = For_scen_cf.coords['strategy'].values
        print(f"Grouping by strategy. Found {len(groups)} strategies: {groups}")
    else:  # category
        # Verify category is a coordinate and get unique values
        if 'category' not in For_scen_cf.coords:
            raise ValueError(f"'category' coordinate not found in For_scen_cf. Cannot group by category.")
        
        groups = np.unique(For_scen_cf.coords['category'].values)
        print(f"Grouping by category. Found {len(groups)} categories: {groups}")
    
    # Process each group separately to reduce memory usage
    for group in groups:
        print(f"Processing {args.group_by} group: {group}")
        
        # Filter For_scen_cf to only include scenarios for this group
        if args.group_by == 'strategy':
            # Direct selection using strategy coordinate
            group_For_scen_cf = For_scen_cf.where(For_scen_cf.strategy == group, drop=True)
        else:  # category
            # Direct selection using category coordinate
            group_For_scen_cf = For_scen_cf.where(For_scen_cf.category == group, drop=True)
        
        # Skip if the group selection is empty
        if group_For_scen_cf.sizes['scen'] == 0:
            print(f"No scenarios found for {args.group_by} group: {group}, skipping")
            continue
            
        print(f"Running OSCAR for {args.group_by} group: {group} with {group_For_scen_cf.sizes['scen']} scenarios")
        
        # Check if we need to split into smaller batches
        MAX_SCENARIOS_PER_BATCH = 2000
        total_scenarios = group_For_scen_cf.sizes['scen']
        
        if total_scenarios > MAX_SCENARIOS_PER_BATCH:
            print(f"Group {group} has {total_scenarios} scenarios, which exceeds the maximum of {MAX_SCENARIOS_PER_BATCH}")
            print(f"Splitting into {(total_scenarios + MAX_SCENARIOS_PER_BATCH - 1) // MAX_SCENARIOS_PER_BATCH} parts")
            
            # Get all scenario names
            all_scenarios = group_For_scen_cf.scen.values
            
            # Process each batch
            for batch_idx, batch_start in enumerate(range(0, total_scenarios, MAX_SCENARIOS_PER_BATCH)):
                batch_end = min(batch_start + MAX_SCENARIOS_PER_BATCH, total_scenarios)
                batch_scenarios = all_scenarios[batch_start:batch_end]
                
                print(f"Processing {args.group_by} group: {group} - Part {batch_idx+1} with {len(batch_scenarios)} scenarios (scenarios {batch_start+1}-{batch_end} of {total_scenarios})")
                
                # Select just this batch of scenarios
                batch_For_scen_cf = group_For_scen_cf.sel(scen=batch_scenarios)
                
                # Define part-specific output file
                cf_output_file_batch = f'{export_folder}/Out_scen_cf_{args.nmc}mc_{args.group_by}_{group}_part{batch_idx+1}{chunk_suffix}.nc'
                safe_cf_output_file_batch = get_safe_filepath(cf_output_file_batch)
                
                # Run OSCAR with this batch
                batch_out = run_oscar_with_emissions(Par, Ini, batch_For_scen_cf)
                
                # Save this batch's results
                batch_out.to_netcdf(safe_cf_output_file_batch)
                print(f"Counterfactual scenario results for {args.group_by} group: {group} - Part {batch_idx+1} saved to {safe_cf_output_file_batch}")
                
                # Clean up to free memory
                del batch_For_scen_cf, batch_out
                gc.collect()
        else:
            # Process the entire group as before
            # Define group-specific output file
            cf_output_file_group = f'{export_folder}/Out_scen_cf_{args.nmc}mc_{args.group_by}_{group}{chunk_suffix}.nc'
            safe_cf_output_file_group = get_safe_filepath(cf_output_file_group)
            
            # Run OSCAR with this group
            out_cf_group = run_oscar_with_emissions(Par, Ini, group_For_scen_cf)
            
            # Save this group's results
            out_cf_group.to_netcdf(safe_cf_output_file_group)
            print(f"Counterfactual scenario results for {args.group_by} group: {group} saved to {safe_cf_output_file_group}")
            
            # Clean up to free memory
            del group_For_scen_cf, out_cf_group
            gc.collect()
    

print(f"Chunk {args.chunk_id}/{args.total_chunks} processing complete!") 