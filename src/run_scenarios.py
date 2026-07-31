import os
import xarray as xr
import polars as pl
from AR6_func import run_oscar_with_emissions
import gc
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--nmc", help="Number of MC samples", type=int, default=20)
parser.add_argument("--run", help="Choose which scenarios to run: 'scen', 'cf', or 'both'", 
                    type=str, choices=['scen', 'cf', 'both'], default='both')
args = parser.parse_args()
Par = xr.open_dataset(f'../data/data_raw/AR6_drivers/Par_{args.nmc}mc.nc')
Ini = xr.open_dataset(f'../data/data_raw/AR6_drivers/Ini_{args.nmc}mc.nc')
For_scen = xr.open_dataset(f'../data/data_raw/AR6_drivers/For_scen_AR6_{args.nmc}mc.nc')
category = pl.read_csv('../data/data_man/category.csv')

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

# After updating the Eff values but before stacking
# Create a new dimension with concatenated values instead of using stack

# First, create a list to hold our datasets
datasets = []

# Loop through each strategy
for strat in For_scen_cf.strategy.values:
    # Extract the dataset for this strategy
    # Use .sel() but don't squeeze yet - check if the dimension exists first
    ds = For_scen_cf.sel(strategy=strat)
    
    # Check if 'strategy' is still a dimension (it might be a scalar coordinate now)
    if 'strategy' in ds.dims:
        # If it's still a dimension, squeeze it
        ds = ds.squeeze('strategy')
    
    # Create new scen values by concatenating scen and strategy
    new_scen_values = [f"{s}|{strat}" for s in ds.scen.values]
    
    # Assign these as a new coordinate
    ds = ds.assign_coords(new_scen=('scen', new_scen_values))
    
    # Swap dimensions and drop the old one
    ds = ds.swap_dims({'scen': 'new_scen'})
    ds = ds.rename({'scen': 'scen_ori'})  # Rename to 'scen_ori'
    ds = ds.rename({'new_scen': 'scen'})  # Rename to 'scen'
    
    # Add to our list
    datasets.append(ds)

# Concatenate all datasets along the scen dimension
For_scen_cf = xr.concat(datasets, dim='scen')

export_folder = '../data/data_output/AR6_drivers'
# Save results if needed
if not os.path.exists(export_folder):
    os.makedirs(export_folder)

# Define output file paths
scen_output_file = f'{export_folder}/Out_scen_{args.nmc}mc.nc'
cf_output_file = f'{export_folder}/Out_scen_cf_{args.nmc}mc.nc'

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
    print(f"Running standard scenario with {args.nmc} Monte Carlo samples...")
    safe_scen_output_file = get_safe_filepath(scen_output_file)
    out = run_oscar_with_emissions(Par, Ini, For_scen)
    out.to_netcdf(safe_scen_output_file) 
    del out
    gc.collect()

if args.run in ['cf', 'both']:
    print(f"Running counterfactual scenario with {args.nmc} Monte Carlo samples...")
    safe_cf_output_file = get_safe_filepath(cf_output_file)
    out_cf = run_oscar_with_emissions(Par, Ini, For_scen_cf)
    out_cf.to_netcdf(safe_cf_output_file) 
