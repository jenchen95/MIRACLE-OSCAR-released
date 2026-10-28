import xarray as xr
import numpy as np
import sys
import os
import glob
import re

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oscar.core_fct.mod_process import OSCAR
from oscar.core_fct.fct_misc import aggreg_region, load_data
from oscar.core_fct.fct_loadD import load_landuse_hist, load_RFdrivers_hist, load_landuse_scen, load_RFdrivers_scen


import duckdb
import polars as pl


def hist_init(Par0, Par, mod_region, hist_driver='edrive'):
    """
    Setup OSCAR parameters and calculate historical period once
    
    Returns:
    --------
    tuple
        (Par, Ini, modified_scen_template) containing:
        - Par: OSCAR parameters
        - Ini: Initial conditions from end of historical period
        - modified_scen_template: Template for scenario modifications
    """

    ##################################################
    ## 1. HISTORICAL
    ##################################################

    ## load emissions
    For_hist = aggreg_region(load_data('emissions_CEDS'), mod_region).sum('sector')
    For_hist = For_hist.rename({'E_CO2':'Eff'})

    ## load LULCC
    TMP = load_landuse_hist(mod_region, ['LUH2'], LCC='gross').sel(data_LULCC='LUH2', drop=True)
    For_hist = xr.merge([For_hist, TMP])

    ## load RF drivers
    TMP = load_RFdrivers_hist().sel(data_RF_contr='ICAO', data_RF_solar='CMIP6', data_RF_volc='CMIP6', drop=True)
    For_hist = xr.merge([For_hist, TMP])
    For_hist['RF_contr'] *= 0

    ## load atmospheric concentrations
    TMP = load_data('concentrations_CMIP6').sel(region='Globe', drop=True)
    for VAR in ['CO2', 'CH4', 'N2O', 'Xhalo']:
        For_hist['D_'+VAR] = TMP[VAR] - Par0[VAR+'_0']

    ## missing drivers
    For_hist['Eluc'] = 0*For_hist['Eff']
    For_hist['E_N2O'] = 0*For_hist['Eff']
    For_hist['E_Xhalo'] = 0*For_hist['D_Xhalo']

    ## format and save
    For_hist = For_hist.sel(year=slice(1750, 2014)).fillna(0.)

    if hist_driver == 'edrive':
        print('Dropping D_CO2 to facililate emissions as drivers')
        For_hist = For_hist.drop_vars(['D_CO2'])
    else:
        print('Keeping D_CO2 as drivers')
    For_hist_origin = For_hist.copy()  # Then save the modified version
    
    # Move parameters from For to Par
    Par = xr.merge([Par, For_hist.drop([VAR for VAR in For_hist if 'year' in For_hist[VAR].dims])])
    For_hist = For_hist.drop([VAR for VAR in For_hist if 'year' not in For_hist[VAR].dims])
    
    # Run historical period once
    Out_hist = OSCAR(Ini=None, Par=Par, For=For_hist)
    Ini = Out_hist.isel(year=-1, drop=True)
    
    return Par, Ini, For_hist_origin, Out_hist

def ar6_load():
    """
    Load CO2 emissions and model-scenario pairs data from parquet files and convert to xarray Dataset.
    Returns emissions in Pg C (converted from Mt CO2) and Tg C (converted from Mt CH4) and Tg S (converted from Mt SO2).
    
    Returns:
    --------
    xarray.DataArray
        Emissions scenarios with dimensions (scenario, region, year)
        where scenario is a combination of model and scenario names
    """
    # Load environment variables
    
    # Connect to database using duckdb
    conn = duckdb.connect()
    
    # Query to get emissions data and perform transformations directly in SQL
    query = """
        with co2_ff as (
            SELECT 
                model,
                scenario,
                model || '|' || scenario as scenario_id,
                region,
                'co2_ff' as scope,
                'Pg C' as unit,
                CAST(year AS INTEGER) as year,
                -- Convert Mt CO2 to Pg C: (1/1000) * (12.011/44.009)
                sum(value) * (1.0/1000.0) * (12.011/44.009) as value
            FROM read_parquet('../data/data_raw/AR6_drivers/r10_ghg.parquet')
            WHERE scope in ('co2_energy', 'co2_industry')
            AND year >= 2015
            group by all
        ),
        ch4 as (
            SELECT 
                model,
                scenario,
                model || '|' || scenario as scenario_id,
                region,
                scope,
                'Tg C' as unit,
                CAST(year AS INTEGER) as year,
                -- Convert Mt CH4 to Tg C: 1 * (12.011/16.04)
                value * 1 * (12.011/16.04) as value
            FROM read_parquet('../data/data_raw/AR6_drivers/r10_ghg.parquet')
            WHERE scope = 'ch4'
            AND year >= 2015
        ),
        so2 as (
            SELECT
                model,
                scenario,
                model || '|' || scenario as scenario_id,
                region,
                scope,
                'Tg S' as unit,
                CAST(year AS INTEGER) as year,
                -- Convert Mt SO2 to Tg S: 1 * (32.065/64.066)
                value * 1 * (32.065/64.066) as value
            FROM read_parquet('../data/data_raw/AR6_drivers/r10_ghg.parquet')
            WHERE scope = 'so2'
            AND year >= 2015
        ),
        ghg as (
            select * from co2_ff
            union all
            select * from ch4
            union all
            select * from so2
        ),
        ssp_family as (
            select
                model,
                scenario,
                ssp_detail
            from read_csv('../data/data_man/ssp_family.csv')
        ),
        reg_map as (
            select
                ar6r10,
                rcpr5
            from read_csv('../data/data_man/reg_map.csv')
        ),
        ms as (
            select
                model,
                scenario
            from read_parquet('../data/data_man/opt_set_ms.parquet')
        )
        select
            ssp_family.ssp_detail as ssp,
            scenario_id,
            reg_map.rcpr5 as region,
            scope,
            year,
            sum(value) as value
        from ghg
        join ms on ghg.model = ms.model and ghg.scenario = ms.scenario
        left join ssp_family on ghg.model = ssp_family.model and ghg.scenario = ssp_family.scenario
        join reg_map on ghg.region = reg_map.ar6r10
        group by all
    """
    
    # Execute query and convert to polars DataFrame
    df = pl.from_arrow(conn.execute(query).to_arrow_table())
    
    # First get the SSP mapping to avoid sparse arrays
    ssp_mapping = (df.select(['scenario_id', 'ssp'])
                    .unique()
                    .sort('scenario_id')
                    .to_pandas()
                    .set_index('scenario_id')['ssp']
                    .to_dict())
    
    # Convert to xarray without the sparse ssp dimension
    emissions = (
        df.sort(['scenario_id', 'region'])
        .group_by(['scenario_id', 'region', 'scope', 'year'])
        .agg(pl.col('value').sum())
        .to_pandas()
        .set_index(['scenario_id', 'region', 'scope', 'year'])['value']
        .to_xarray()
        .rename({'scenario_id': 'scenario'})
    )
    
    # Add SSP mapping as a coordinate
    emissions = emissions.assign_coords(ssp=(('scenario'), [ssp_mapping[s] for s in emissions.scenario.values]))
    
    return emissions

def scen_load(Par0, For_hist, mod_region):
    """
        Load original version of For_scen
    """
    # Recreate For_hist just for the 2014 data point


    For_scen = aggreg_region(load_data('emissions_ScenarioMIP'), mod_region, old_axis='region', dataset='ScenarioMIP')
    For_scen = xr.concat([For_scen, For_scen.sel(year=2100).assign_coords(year=2300)], dim='year')

    ## correction: non-CO2 emissions from FF&I decrease to 0, while those from LUC stay constant
    sectors_LU = ['Forest Burning', 'Grassland Burning', 'Peat Burning'] + ['Agricultural Waste Burning', 'Agriculture']
    for var in For_scen.variables:
        if (var not in For_scen.coords)  and  (var not in ['E_N2O', 'Eluc']):
            For_scen[var].loc[{'sector':[sec for sec in For_scen.sector.values if sec not in sectors_LU], 'year':2300}] = 0.
    For_scen = For_scen.interp(year=np.arange(2015, 2300+1)).sum('sector')

    ## specific treatment for Eff. Does not follow O'Neill et al, 2016, but updates of extensions from the poster of Meinshausen 2019 (ScenarioForum).
    dico_dates_end_plateau = {'SSP1-1.9':2140, 'SSP1-2.6':2140, 'SSP2-4.5':2100, 'SSP3-7.0':2100, 'SSP3-7.0-LowNTCF':2100, 'SSP4-3.4':2140, 'SSP4-6.0':2100, 'SSP5-3.4-OS':2140, 'SSP5-8.5':2100}
    dico_dates_end_ramp = { 'SSP1-1.9':2190, 'SSP1-2.6':2190, 'SSP2-4.5':2250, 'SSP3-7.0':2250, 'SSP3-7.0-LowNTCF':2250, 'SSP4-3.4':2190, 'SSP4-6.0':2250, 'SSP5-3.4-OS':2170, 'SSP5-8.5':2250 }

    for scen in For_scen.scen.values:
        # Get the value at 2100 for this scenario
        val_2100 = For_scen['Eff'].sel(scen=scen, year=2100)
        
        # Constant plateau period
        plateau_years = range(2100, dico_dates_end_plateau[scen]+1)
        For_scen['Eff'].loc[dict(scen=scen, year=plateau_years)] = val_2100
        
        # Linear ramp down period
        ramp_years = np.arange(dico_dates_end_plateau[scen], dico_dates_end_ramp[scen]+1)
        ramp_values = np.linspace(1, 0, dico_dates_end_ramp[scen]-dico_dates_end_plateau[scen]+1)
        for i, year in enumerate(ramp_years):
            For_scen['Eff'].loc[dict(scen=scen, year=year)] = val_2100 * ramp_values[i]
        
        # Zero afterwards
        zero_years = np.arange(dico_dates_end_ramp[scen]+1, 2300+1)
        For_scen['Eff'].loc[dict(scen=scen, year=zero_years)] = 0.

    ## specific treatment for Eluc
    eluc_2100 = For_scen['Eluc'].sel(year=2100)
    ramp_years = np.arange(2100, 2150+1)
    ramp_values = np.linspace(1, 0, 2150-2100+1)
    for i, year in enumerate(ramp_years):
        For_scen['Eluc'].loc[dict(year=year)] = eluc_2100 * ramp_values[i]

    For_scen['Eluc'].loc[dict(year=np.arange(2150+1, 2300+1))] = 0.

    ## load LULCC
    TMP = load_landuse_scen(mod_region, ['LUH2'], LCC='gross').rename({'scen_LULCC':'scen'})
    TMP.coords['scen'] = [scen + '-OS' * (scen == 'SSP5-3.4') for scen in TMP['scen'].values]
    TMP = TMP.where(TMP.year < 2100).dropna('year')
    TMP = xr.concat([TMP, TMP.sel(year=2099).assign_coords(year=2300)], dim='year')
    TMP = TMP.interp(year=np.arange(850, 2300+1))
    TMP['d_Acover'] = TMP['d_Acover'].where(TMP.year <= 2099, 0)
    For_scen = xr.merge([For_scen, TMP])

    ## load RF drivers
    TMP = load_RFdrivers_scen().sel(scen_RF_contr='CMIP5', scen_RF_solar='CMIP6', scen_RF_volc='CMIP6', drop=True)
    for VAR in TMP:
        years = (For_hist[VAR].dropna('year').year + TMP[VAR].dropna('year').year).year
        For_scen[VAR] = For_hist[VAR].sel(year=years).mean('year') / TMP[VAR].sel(year=years).mean('year') * TMP[VAR]

    ## load atmospheric concentrations
    TMP = load_data('concentrations_ScenarioMIP').drop_vars('Xhalo_eq')
    for VAR in ['CO2', 'CH4', 'N2O', 'Xhalo']:
        For_scen['D_'+VAR] = TMP[VAR] - Par0[VAR+'_0']

    ## missing drivers
    For_scen['E_Xhalo'] = 0*For_scen['D_Xhalo']

    ## format and save
    For_scen = For_scen.sel(year=slice(2015, 2300))
    For_scen = xr.concat([For_hist.sel(year=2014).drop_vars('Aland_0'), For_scen], dim='year')
    For_scen = For_scen.drop_vars(['D_CO2', 'D_CH4'])
    For_scen['Eff'] = For_scen['Eff'].where(For_scen.reg_land != 0, 0)
    For_scen['E_CH4'] = For_scen['E_CH4'].where(For_scen.reg_land != 0, 0)
    
    return For_scen


def scen_update(For_scen, emission_series):
    """
    Update the emission series with the new emissions data

    For_scen: scen data from SSP
    emission_series: xarray.DataArray
        Time series of regional CO2 emissions (Eff) and CH4 emissions (E_CH4) with dimensions (scenario, ssp, region, year)
    """
    # Create a copy of the scenario template to expand
    modified_scen = For_scen.copy(deep=True)
    
    # Create mapping from long names to reg_land codes
    region_mapping = dict(zip(
        modified_scen.reg_land_long_name.values,
        modified_scen.reg_land.values
    ))

    # Get unique SSPs to avoid duplicating scenarios
    unique_ssps = np.unique(emission_series.ssp.values)
    new_scenarios = []

    # For each SSP, create the base scenario only once
    for ssp in unique_ssps:
        try:
            # Get all scenario_ids for this SSP
            scenario_ids = emission_series.scenario.where(emission_series.ssp == ssp, drop=True)
            
            # Create base scenario from SSP only once
            base_scenario = modified_scen.sel(scen=ssp).copy(deep=True)
            
            # Create and update each new scenario
            for scenario_id in scenario_ids:
                # Create new scenario with the correct dimensions
                new_scenario = xr.Dataset(
                    data_vars={
                        var: (base_scenario[var].dims, base_scenario[var].values)
                        for var in base_scenario.data_vars
                    },
                    coords={
                        coord: base_scenario[coord].values
                        for coord in base_scenario.coords if coord not in ['scen', 'reg_land_long_name']
                    }
                )
                new_scenario = new_scenario.expand_dims(scen=[scenario_id.item()]).copy(deep=True)
                
                # Update emissions for each region
                scenario_emissions = emission_series.sel(scenario=scenario_id)
                for region in scenario_emissions.region.values:
                    try:
                        print(f'Now updating {region} in {scenario_id} of {ssp}')
                        reg_code = region_mapping[region]
                        region_data_co2_ff = scenario_emissions.sel(region=region, scope='co2_ff').sortby('year').squeeze().to_numpy()
                        region_data_ch4 = scenario_emissions.sel(region=region, scope='ch4').sortby('year').squeeze().to_numpy()
                        region_data_so2 = scenario_emissions.sel(region=region, scope='so2').sortby('year').squeeze().to_numpy()
                        new_scenario['Eff'].loc[dict(scen=scenario_id, reg_land=reg_code, year=slice(2015, 2100))] = region_data_co2_ff
                        new_scenario['E_CH4'].loc[dict(scen=scenario_id, reg_land=reg_code, year=slice(2015, 2100))] = region_data_ch4
                        if not scenario_id.to_numpy().tolist().startswith('TIAM'):
                            # For TIAM model, set SO2 emissions to default OSCAR values, otherwise use AR6 data
                            new_scenario['E_SO2'].loc[dict(scen=scenario_id, reg_land=reg_code, year=slice(2015, 2100))] = region_data_so2
                    except KeyError as e:
                        print(f"Warning: Could not find region '{region}' in OSCAR's regions")
                        continue
                if not scenario_id.to_numpy().tolist().startswith('TIAM'):
                    # For TIAM model, set SO2 emissions to default OSCAR values, otherwise use AR6 data. Here 0-th reg_land's SO2 emissions are set to 0
                    new_scenario['E_SO2'].loc[dict(scen=scenario_id, reg_land=0, year=slice(2015, 2100))] = 0
                
                new_scenarios.append(new_scenario)
                    
        except KeyError as e:
            print(f"Warning: Could not find SSP scenario '{ssp}' in OSCAR's scenarios")
            continue
    
    # Combine all scenarios
    if new_scenarios:
        new_scenarios = xr.concat(new_scenarios, dim='scen')
    
    # Limit years to 2100 as in original code
    new_scenarios = new_scenarios.sel(year=slice(None, 2100))

    category_mapping = (
        pl.read_csv('../data/data_man/category.csv')
        .with_columns(
            scen = pl.col('model') + '|' + pl.col('scenario')
        )
        .select(['scen', 'category'])
        .unique()
        .sort('scen')
        .to_pandas()
        .set_index('scen')['category']
        .to_dict()
    )

    new_scenarios = new_scenarios.assign_coords(category=(('scen'), [category_mapping[s] for s in new_scenarios.scen.values]))
    
    return new_scenarios


def run_oscar_with_emissions(Par, Ini, For_scen):
    """
    Run OSCAR with modified emission scenarios using pre-calculated initial conditions
    
    Parameters:
    -----------
    Par: xarray.Dataset
        OSCAR parameters
    Ini: xarray.Dataset
        Initial conditions from historical run
        
    Returns:
    --------
    xarray.Dataset
        OSCAR output including D_Tg (global temperature change)
    """
    # Define variables to keep in output
    var_keep = []
    
    # Run scenario period
    Out_scen = (
        OSCAR(Ini=Ini, Par=Par, For=For_scen, var_keep=var_keep, nt=4, adapt_nt=False)
        [['D_Tg', 'D_CO2', 'D_CH4']]
    )

    category_mapping = (
        pl.read_csv('../data/data_man/category.csv')
        .with_columns(
            scen = pl.col('model') + '|' + pl.col('scenario')
        )
        .select(['scen', 'category'])
        .unique()
        .sort('scen')
        .to_pandas()
        .set_index('scen')['category']
        .to_dict()
    )

    if 'scen_ori' in Out_scen.coords:
        # Instead of using scen_ori, extract model|scenario from scen values
        # and apply category mapping to those extracted values
        extracted_keys = []
        for s in Out_scen.scen.values:
            # Extract model|scenario part from scen (assuming format is model|scenario|strategy)
            parts = s.split('|')
            if len(parts) >= 2:
                # Take first two parts (model|scenario)
                extracted_key = '|'.join(parts[:2])
                extracted_keys.append(extracted_key)
            else:
                # If format is unexpected, use the original string
                extracted_keys.append(s)
        
        # Assign category coordinate to scen dimension using the extracted keys
        Out_scen = Out_scen.assign_coords(category=(('scen'), [category_mapping.get(key, 'unknown') 
                                                              for key in extracted_keys]))
    else:
        # Fall back to using scen if scen_ori doesn't exist
        Out_scen = Out_scen.assign_coords(category=(('scen'), [category_mapping.get(s, 'unknown') for s in Out_scen.scen.values]))
    
    return Out_scen 

def calculate_weights(historical_data, period_base=(1850, 1900), historical_base=None, period_compare=(1995, 2014), 
                      observed_mean=0.85, observed_std=0.079, save_path=None) -> xr.DataArray:
    """
    Calculate weights based on the global temperature change.
    
    Parameters:
    -----------
    historical_data: xarray.Dataset or xarray.DataArray
        Historical data containing D_Tg (global temperature change)
    period_base: tuple, optional
        Base period for temperature calculation (default: 1850-1900)
    period_compare: tuple, optional
        Comparison period for temperature calculation (default: 1995-2014)
    observed_mean: float, optional
        Observed mean temperature change (default: 0.85)
    observed_std: float, optional
        Observed standard deviation of temperature change (default: 0.079)
    save_path: str, optional
        Path to save the weights, if None the weights are not saved
        
    Returns:
    --------
    xarray.Dataset
        Dataset containing the calculated weights
    """
    
    # Calculate base period mean
    if historical_base is None:
        historical_base = historical_data.sel(year=slice(*period_base))
        historical_base_mean = historical_base.mean("year")
    else:
        historical_base_mean = historical_base
    
    # Calculate comparison period mean
    historical_compare = historical_data.sel(year=slice(*period_compare))
    historical_compare_mean = historical_compare.mean("year")
    
    # Calculate temperature change
    historical_change_mean = historical_compare_mean - historical_base_mean
    
    # Calculate weights using Gaussian distribution
    weights = (
        1
        / observed_std
        / np.sqrt(2 * np.pi)
        * np.exp(-0.5 * (historical_change_mean - observed_mean) ** 2 / observed_std**2)
    )
    
    # Normalize weights
    normalized_weights = weights / weights.sum("config")
    
    # Create dataset to hold the weights
    weight_ds = xr.DataArray(data=normalized_weights, dims='config')
    
    # Save the weights if a save path is provided
    if save_path is not None:
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        weight_ds.to_netcdf(save_path)
        print(f"Saved weights to {save_path}")
    
    return weight_ds

def weighted_stats(data: xr.DataArray, weights: xr.DataArray, stats_dim: str = 'config'):
    """
    Calculates the weighted mean and standard deviation of a DataArray.

    Args:
        data (xr.DataArray): The input DataArray.
        weights (xr.DataArray): The weights to apply.

    Returns:
        Tuple[xr.DataArray, xr.DataArray]: The weighted mean, standard
            deviation, median, 33rd percentile, and 66th percentile.
    """
    weights = weights.fillna(0)
    
    # Normalize weights to sum to 1.0 along the stats_dim
    normalized_weights = weights / weights.sum(dim=stats_dim)
    
    weighted_data = data.weighted(normalized_weights)

    mean = weighted_data.mean(dim=stats_dim)

    std = weighted_data.std(dim=stats_dim)

    median, p33, p66 = weighted_data.quantile([0.5, 0.33, 0.66], dim=stats_dim).drop_vars('quantile')

    return mean, std, median, p33, p66


def concat_multidim_files(pattern, nmc, chunksize=100, var_keep='D_Tg', save_path=None):
    """
    Process multidimensional files by concatenating along the 'config' dimension
    for each category and part group, saving each as a separate file.
    
    Parameters:
    -----------
    pattern: str
        File pattern to search for, e.g., 'Out_scen_cf_{nmc}mc*.nc'
    nmc: int
        Number of Monte Carlo samples
    var_keep: list, optional
        List of variables to keep, if None keeps all variables
    save_path: str, optional
        Base path for saving files. Each group will be saved with a suffix.
        If None, no files are saved.
        
    Returns:
    --------
    list
        List of paths to saved files
    """
    # Replace {nmc} with the actual value
    file_pattern = pattern.format(nmc=nmc)
    
    # Get all matching files
    all_files = glob.glob(file_pattern)
    if not all_files:
        raise FileNotFoundError(f"No files found matching pattern: {file_pattern}")
    
    saved_files = []
    
    # For counterfactual scenario files, process by category and part
    if 'cf' in pattern:
        # Extract categories and parts from filenames
        pattern_regex = rf'.*_{nmc}mc_category_([^_]+)_part(\d+)_(\d+)of{chunksize}\.nc'
        
        # Group files by category and part
        groups = {}  # keys will be (category, part) tuples
        
        for file in all_files:
            filename = os.path.basename(file)
            match = re.search(pattern_regex, filename)
            if match:
                category = match.group(1)  # Category (e.g., C1, C3)
                config = match.group(3)    # Config number
                key = (category, config)
                
                if key not in groups:
                    groups[key] = []
                groups[key].append(file)
        
        # Process each group separately, concatenating only along the 'config' dimension
        # Sort groups by category and numerical config to ensure proper order
        for (category, config) in sorted(groups.keys(), key=lambda x: (x[0], int(x[1]))):
            files = groups[(category, config)]
            if files:
                # Sort files based on the numeric order in the filename (e.g., 1of100, 2of100, etc.)
                sorted_files = sorted(files, key=lambda x: int(re.search(r'(\d+)of\d+\.nc$', x).group(1)))
                print(f'Loading {len(sorted_files)} files for category {category} config {config}')
                # Combine all configs for this category and part
                group_data = []
                for file in sorted_files:
                    group_data.append(xr.open_dataset(file))
                group_data = xr.concat(group_data, dim='scen', coords='minimal')
                
                group_data = group_data.sortby(['scen_ori', 'strategy'])
                
                # Keep only specified variables if requested
                if var_keep is not None:
                    group_data = group_data[var_keep]
                
                # Save each group as a separate file if save_path is provided
                if save_path is not None:
                    # Create base directory if it doesn't exist
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    
                    # Determine save path for this group
                    # Extract base name and extension from save_path
                    base_name, extension = os.path.splitext(save_path)
                    group_save_path = f"{base_name}_category_{category}_{config}of{chunksize}{extension}"
                    
                    # Fix serialization warning for object dtype variables (like category)
                    # Instead of converting to fixed-length strings, prepare proper encoding for netCDF
                    encoding = {}
                    for var_name in group_data.variables:
                        var = group_data[var_name]
                        # Handle both coordinates and data variables with object dtype
                        if hasattr(var.data, 'dtype') and var.dtype == 'O':
                            print(f"Setting variable-length string encoding for {var_name}")
                            encoding[var_name] = {'dtype': str}
                    
                    # Specifically handle the 'scen' coordinate to avoid truncation
                    # Check the maximum length of scen values
                    if 'scen' in group_data.coords:
                        max_scen_length = max(len(str(s)) for s in group_data.scen.values)
                        # Set a safe length (add some buffer)
                        safe_length = max(max_scen_length + 20, 150)  # At least 150 chars
                        encoding['scen'] = {'dtype': f'U{safe_length}'}
                        print(f"Setting scen encoding to U{safe_length} to handle long scenario names")
                    
                    # Save the group data with proper string encoding
                    group_data.to_netcdf(group_save_path, encoding=encoding)
                    print(f"Saved group file to {group_save_path}")
                    saved_files.append(group_save_path)
                
                # Close the dataset to free memory
                group_data.close()
        
        # Return the list of saved files
        return saved_files
                
    else:
        # For simpler files without category/part/config structure
        combined_data = xr.open_mfdataset(file_pattern, combine='nested', concat_dim='config')
        
        # Keep only specified variables if requested
        if var_keep is not None:
            combined_data = combined_data[var_keep]
        
        # Save the result if a save path is provided
        if save_path is not None:
            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # Fix serialization warning for object dtype variables
            # Use variable-length string encoding instead of fixed-width strings
            encoding = {}
            for var_name in combined_data.variables:
                var = combined_data[var_name]
                if hasattr(var.data, 'dtype') and var.dtype == 'O':
                    print(f"Setting variable-length string encoding for {var_name}")
                    encoding[var_name] = {'dtype': str}
            
            # Save with proper string encoding
            combined_data.to_netcdf(save_path, encoding=encoding)
            print(f"Saved concatenated file to {save_path}")
            saved_files.append(save_path)
        
        # Return the combined data for non-cf files
        return saved_files if save_path is not None else combined_data
