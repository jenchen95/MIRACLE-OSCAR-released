## general imports
import os
import numpy as np
import argparse
import xarray as xr
import warnings
import sys

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

## specific imports
from oscar.core_fct.fct_loadP import load_all_param
from oscar.core_fct.fct_genMC import generate_config
from AR6_func import hist_init, ar6_load, scen_load, scen_update


## OPTIONS
parser = argparse.ArgumentParser()
parser.add_argument("--nmc", help="Number of MC samples", type=int, default=200)
parser.add_argument("--reload_hist", help="Decide whether reload the calculation of historical data", action="store_true", default=False)
parser.add_argument("--hist_driver", help="Choose which historical driver to use: concentration-based or emission-based", type=str, choices=['cdrive', 'edrive'], default='edrive')
parser.add_argument("--reload_scen", help="Decide whether reload For_scen data", action="store_true", default=False)
parser.add_argument("--reload_ar6", help="Decide whether reload ar6 emission data", action="store_true", default=False)
parser.add_argument("--scen_update", help="Decide whether update For_scen data with emission series", action="store_true", default=False)
args = parser.parse_args()

# If reload_hist is True, force reload_scen to be True as well
if args.reload_hist:
    args.reload_scen = True
    args.scen_update = True

if args.reload_ar6 or args.scen_update:
    args.scen_update = True

folder_out = '../data/data_raw/AR6_drivers/'
mod_region = 'RCP_5reg'

# Check if the output directory exists, create it if not
if not os.path.isdir(folder_out):
    warnings.warn(f"Output directory {folder_out} does not exist. Creating it now.")
    os.makedirs(folder_out, exist_ok=True)


## If reload arg is true, it will recalculate historical data
if args.reload_hist: 
    Par0 = load_all_param(mod_region)
    Par = generate_config(Par0, nMC=args.nmc)## create output folder
    Par, Ini, For_hist_origin, Out_hist = hist_init(Par0, Par, mod_region, hist_driver=args.hist_driver)
    Par.to_netcdf(folder_out + f'Par_{args.nmc}mc.nc', encoding={var: {'zlib':True, 'dtype': np.float32} for var in Par})
    Ini.to_netcdf(folder_out + f'Ini_{args.nmc}mc.nc', encoding={var: {'zlib':True, 'dtype': np.float32} for var in Ini})
    For_hist_origin.to_netcdf(folder_out + f'For_hist_origin_{args.nmc}mc.nc', encoding={var: {'zlib':True, 'dtype': np.float32} for var in For_hist_origin})
    Out_hist.to_netcdf(folder_out + f'Out_hist_{args.nmc}mc.nc', encoding={var: {'zlib':True, 'dtype': np.float32} for var in Out_hist})

else:
    pass

if args.reload_scen:
    if not args.reload_hist:
        Par0 = load_all_param(mod_region)
    For_hist_origin = xr.open_dataset(folder_out + f'For_hist_origin_{args.nmc}mc.nc')
    For_scen = scen_load(Par0, For_hist_origin, mod_region)
    For_scen.to_netcdf(folder_out + f'For_scen_SSP_{args.nmc}mc.nc', 
                       encoding={
                           var: {'zlib': True, 'dtype': np.float32} for var in For_scen.data_vars
                       } | {
                           'scen': {'dtype': 'str'}
                       })
else:
    try:
        For_scen = xr.open_dataset(folder_out + f'For_scen_SSP_{args.nmc}mc.nc')
    except FileNotFoundError:
        warnings.warn(f"File not found: {folder_out}For_scen_SSP_{args.nmc}mc.nc. Please run with --reload_scen first.")
        exit(1)

if args.reload_ar6:
    emissions_ar6 = ar6_load()
    emissions_ar6.to_netcdf(folder_out + 'emissions_ar6.nc')
else:
    try:
        emissions_ar6 = xr.open_dataset(folder_out + 'emissions_ar6.nc').to_array()
    except FileNotFoundError:
        warnings.warn(f"File not found: {folder_out}emissions_ar6.nc. Please run with --reload_ar6 first.")
        exit(1)

if args.scen_update:
    For_scen = scen_update(For_scen, emissions_ar6)
    For_scen.to_netcdf(folder_out + f'For_scen_AR6_{args.nmc}mc.nc', 
                       encoding={
                           var: {'zlib': True, 'dtype': np.float32} for var in For_scen.data_vars
                       } | {
                           'scen': {'dtype': 'str'}
                       })
else:
    try:
        For_scen = xr.open_dataset(folder_out + f'For_scen_AR6_{args.nmc}mc.nc')
    except FileNotFoundError:
        warnings.warn(f"File not found: {folder_out}For_scen_AR6_{args.nmc}mc.nc. Please run with --scen_update first.")
        exit(1)

