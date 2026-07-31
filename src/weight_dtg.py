import xarray as xr
import argparse
from AR6_func import calculate_weights, weighted_stats
import glob
import polars as pl
import gc
import re
import os
import numpy as np
import dask

# Configure Dask to optimize for large arrays
dask.config.set({"array.slicing.split_large_chunks": True})

parser = argparse.ArgumentParser()
parser.add_argument("--nmc", type=int, default=2000)
parser.add_argument("--calc_weights", type=bool, default=True)
parser.add_argument("--run", type=str, choices=['scen', 'cf', 'both'], default='both', help="Run calculations for scenarios, counterfactuals, or both")
parser.add_argument("--weight_level", type=str, choices=['strategy', 'scen', 'both'], default='both', help="Calculate weights at strategy level, scenario level, or both in counterfactuals")
parser.add_argument("--compound_weights", type=bool, default=False)
parser.add_argument("--chunksize", type=int, default=100)

args = parser.parse_args()
base_dir = "../data/data_output/AR6_drivers"
hist_dir = "../data/data_raw/AR6_drivers"


if __name__ == "__main__":
    if not args.calc_weights:
        print("Loading weight_dtg")
        weight_dtg = xr.open_dataarray(f"../data/data_output/AR6_drivers/weight_dtg_{args.nmc}mc.nc")

    else:
        print("Calculating weight_dtg")
        if not args.compound_weights:
            print("Calculating weight_dtg without compound concentration weights")
            d_tg = xr.open_dataset(f"{hist_dir}/Out_hist_{args.nmc}mc.nc").D_Tg
            weight_dtg = calculate_weights(d_tg, save_path=f"{base_dir}/weight_dtg_{args.nmc}mc.nc")
        else:
            print("Calculating weight_dtg with compound concentration weights")
            d_tg = xr.open_dataset(f"{hist_dir}/Out_hist_{args.nmc}mc.nc").D_Tg
            weight_dtg = calculate_weights(d_tg, save_path=f"{base_dir}/weight_dtg_{args.nmc}mc.nc")
            d_co2 = xr.open_dataset(f"{hist_dir}/Out_hist_{args.nmc}mc.nc").D_CO2
            weight_dco2 = calculate_weights(d_co2, save_path=f"{base_dir}/weight_dco2_{args.nmc}mc.nc", historical_base=-278.29998779296875, period_compare=(2010, 2014), observed_mean=392.95, observed_std=3.48)  # 2010-2014, co2 concentration

            ## w2：combined w1 + w2
            # Now combine weights with consistent variable name
            combined_weight = (weight_dtg * weight_dco2)/(weight_dtg * weight_dco2).sum('config')

            # Save the combined weight
            combined_weight.to_netcdf(f"{base_dir}/weight_combined_{args.nmc}mc.nc")

            # Use combined_weight for further operations
            weight_dtg = combined_weight

    pattern_hist = f"{hist_dir}/Out_hist_{args.nmc}mc.nc"
    pattern_scen = f"{base_dir}/Out_scen_{args.nmc}mc*.nc"
    pattern_cf = f"{base_dir}/Out_scen_cf_{args.nmc}mc*.nc"

    hist_files = glob.glob(pattern_hist)
    scen_files = glob.glob(pattern_scen)
    cf_files = glob.glob(pattern_cf)

    print(f"Found {len(hist_files)} historical files (Off course!), {len(scen_files)} scenario files and {len(cf_files)} counterfactual files")

    # Always process historical files
    print(f"Processing historical file: {hist_files[0]}")
    hist = xr.open_dataset(hist_files[0]).D_Tg
    hist_mean, hist_std, hist_median, hist_p33, hist_p66 = weighted_stats(hist, weight_dtg)

    # Create a dictionary of measures and their data
    measures = {
        'mean': hist_mean,
        'std': hist_std,
        'median': hist_median,
        'p33': hist_p33,
        'p66': hist_p66
    }
    
    # Process all measures in a single operation
    combined_df = None
    for measure_name, measure_data in measures.items():
        df = pl.DataFrame(measure_data.to_dataframe(measure_name).reset_index())
        df = df.with_columns(pl.lit(measure_name).alias('measure'))
        df = df.with_columns(pl.lit('historical').alias('scen'))
        df = df.with_columns(pl.lit('HIST').alias('category'))
        df = df.rename({measure_name: 'value'})
        
        if combined_df is None:
            combined_df = df
        else:
            combined_df = pl.concat([combined_df, df])
    
    # Write to a single parquet file
    combined_df.write_parquet(f"{base_dir}/dtg_weighted_hist_{args.nmc}mc.parquet")
    
    # Clean up memory once
    del combined_df, hist_mean, hist_std, hist_median, hist_p33, hist_p66
    gc.collect()

    print('Historical weighted mean, std, median, p33, p66 done')
    
    # Process scenario files if run is 'scen' or 'both'
    if args.run in ['scen', 'both']:
        print(f"Processing scenario files (run={args.run})")
        
        # Load and process all scenario files at once
        scen_datasets = [xr.open_dataset(file).D_Tg for file in scen_files]
        scen_combined = xr.concat(scen_datasets, dim="scen")
        
        # Calculate statistics for all scenarios at once
        scen_mean, scen_std, scen_median, scen_p33, scen_p66 = weighted_stats(scen_combined, weight_dtg)
        
        # Create a dictionary of measures and their data
        measures = {
            'mean': scen_mean,
            'std': scen_std,
            'median': scen_median,
            'p33': scen_p33,
            'p66': scen_p66
        }
        
        # Process all measures in a single operation
        combined_df = None
        for measure_name, measure_data in measures.items():
            df = pl.DataFrame(measure_data.to_dataframe(measure_name).reset_index())
            df = df.with_columns(pl.lit(measure_name).alias('measure'))
            df = df.rename({measure_name: 'value'})
            
            if combined_df is None:
                combined_df = df
            else:
                combined_df = pl.concat([combined_df, df])
        
        # Write to a single parquet file
        combined_df.write_parquet(f"{base_dir}/dtg_weighted_scen_{args.nmc}mc.parquet")
        
        # Clean up memory
        del combined_df, scen_mean, scen_std, scen_median, scen_p33, scen_p66, scen_datasets
        gc.collect()
        print('Scenario weighted mean, std, median, p33, p66 done')

        categories = np.unique(scen_combined.category)

        combined_df = []
        for category in categories:
            print(f"Processing category: {category}")
            scen_category = scen_combined.where(scen_combined.category == category, drop=True)
            cate_mean, cate_std, cate_median, cate_p33, cate_p66 = weighted_stats(scen_category.stack(scen_config=('scen', 'config')), weight_dtg.expand_dims({'scen': scen_category.scen}).stack(scen_config=('scen', 'config')), stats_dim='scen_config')

            measures = {
                'mean': cate_mean,
                'std': cate_std,
                'median': cate_median,
                'p33': cate_p33,
                'p66': cate_p66
            }

            combined_df_category = None
            for measure_name, measure_data in measures.items():
                df = pl.DataFrame(measure_data.to_dataframe(measure_name).reset_index())
                df = df.with_columns(pl.lit(measure_name).alias('measure'))
                df = df.rename({measure_name: 'value'})
                df = df.with_columns(pl.lit(category).alias('category'))

                if combined_df_category is None:
                    combined_df_category = df
                else:
                    combined_df_category = pl.concat([combined_df_category, df])

            combined_df.append(combined_df_category)

        combined_df = pl.concat(combined_df)
        combined_df.write_parquet(f"{base_dir}/dtg_weighted_scen_{args.nmc}mc_category_all.parquet")

        del combined_df, cate_mean, cate_std, cate_median, cate_p33, cate_p66
        gc.collect()

    # Process counterfactual files if run is 'cf' or 'both'
    if args.run in ['cf', 'both']:
        print(f"Processing counterfactual files (run={args.run})")
        # Group counterfactual files by category
        cf_by_category = {}
        pattern_regex = rf'.*_{args.nmc}mc_category_([^_]+)_(\d+)of{args.chunksize}\.nc'
        
        for file in cf_files:
            filename = os.path.basename(file)
            match = re.search(pattern_regex, filename)
            if match:
                category = match.group(1)
                if category not in cf_by_category:
                    cf_by_category[category] = []
                cf_by_category[category].append(file)
        
        # Sort files by their numeric part for each category
        for category in cf_by_category:
            cf_by_category[category].sort(key=lambda x: int(re.search(rf'.*_{args.nmc}mc_category_{category}_(\d+)of{args.chunksize}\.nc', os.path.basename(x)).group(1)))
        
        # Process files by category
        for category, files in cf_by_category.items():
            print(f"Processing counterfactual files for category: {category} ({len(files)} files)")
            
            # Strategy-level processing
            if args.weight_level in ['strategy', 'both']:
                print(f"Processing {category} at strategy level (weight_level={args.weight_level})")
                # Only chunk the year dimension, keep config dimension whole
                cf = (
                    xr.open_mfdataset(files, combine='nested', concat_dim=['config'], 
                                       coords='minimal', compat='override', 
                                       chunks={'year': 5}).D_Tg
                )
                    
                cf = (
                    cf.where(cf['strategy'].compute().notnull(), drop=True)
                    .set_index(scen=('scen_ori', 'strategy'))
                    .unstack('scen')
                )

                cf_mean, cf_std, cf_median, cf_p33, cf_p66 = weighted_stats(
                    cf.stack(scen_config=('scen_ori', 'config')).chunk({'scen_config': -1}), 
                    weight_dtg.expand_dims({'scen_ori': cf.scen_ori}).stack(scen_config=('scen_ori', 'config')).chunk(dict(scen_config=-1)), 
                    stats_dim='scen_config'
                )
                
                # Execute computation here before converting to Polars
                cf_mean, cf_std, cf_median, cf_p33, cf_p66 = dask.compute(
                    cf_mean, cf_std, cf_median, cf_p33, cf_p66
                )

                # Create a dictionary of measures and their data
                measures = {
                    'mean': cf_mean,
                    'std': cf_std,
                    'median': cf_median,
                    'p33': cf_p33,
                    'p66': cf_p66
                }
                
                # Process all measures in a single operation
                combined_df = None
                for measure_name, measure_data in measures.items():
                    df = pl.DataFrame(measure_data.to_dataframe(measure_name).reset_index())
                    df = df.with_columns(pl.lit(category).alias('category'))
                    df = df.with_columns(pl.lit(measure_name).alias('measure'))
                    df = df.rename({measure_name: 'value'})
                    
                    if combined_df is None:
                        combined_df = df
                    else:
                        combined_df = pl.concat([combined_df, df])
                
                # Write to a single parquet file
                combined_df.write_parquet(f"{base_dir}/dtg_weighted_cf_{args.nmc}mc_category_{category}_strategy_all.parquet")
                
                # Clean up memory once
                del combined_df, cf_mean, cf_std, cf_median, cf_p33, cf_p66
                gc.collect()

                print(f'Strategy-level processing completed for {category}')

            # Scenario-level processing
            if args.weight_level in ['scen', 'both']:
                print(f"Processing {category} at scenario level (weight_level={args.weight_level})")
                # Only chunk the year dimension, keep config dimension whole
                cf = (xr.open_mfdataset(files, combine='nested', concat_dim='config', coords='minimal', compat='override',
                                       chunks={'year': 5}).D_Tg
                                  )
                
                cf = (cf.where(cf['strategy'].compute().notnull(), drop=True))

                # Keep config dimension whole by explicitly chunking it to a single chunk
                cf_mean, cf_std, cf_median, cf_p33, cf_p66 = weighted_stats(cf.chunk({'config': -1}), weight_dtg)
                
                # Execute computation here before converting to Polars
                cf_mean, cf_std, cf_median, cf_p33, cf_p66 = dask.compute(
                    cf_mean, cf_std, cf_median, cf_p33, cf_p66
                )

                # Create a dictionary of measures and their data
                measures = {
                    'mean': cf_mean,
                    'std': cf_std,
                    'median': cf_median,
                    'p33': cf_p33,
                    'p66': cf_p66
                }
                
                # Process all measures in a single operation
                combined_df = None
                for measure_name, measure_data in measures.items():
                    df = pl.DataFrame(measure_data.to_dataframe(measure_name).reset_index())
                    df = df.select(pl.exclude('scen_ori', 'strategy'))
                    df = df.with_columns(pl.lit(measure_name).alias('measure'))
                    df = df.rename({measure_name: 'value'})
                    
                    if combined_df is None:
                        combined_df = df
                    else:
                        combined_df = pl.concat([combined_df, df])
                
                # Write to a single parquet file
                combined_df.write_parquet(f"{base_dir}/dtg_weighted_cf_{args.nmc}mc_category_{category}_scen_all.parquet")
                
                # Clean up memory once
                del combined_df, cf_mean, cf_std, cf_median, cf_p33, cf_p66
                gc.collect()

                print(f'Scenario-level processing completed for {category}')

    print('All done')
