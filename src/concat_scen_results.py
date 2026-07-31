import argparse
import os
from AR6_func import concat_multidim_files

# Set up argument parser
parser = argparse.ArgumentParser(description="Concatenate scenario and counterfactual files")
parser.add_argument("--nmc", type=int, default=2000, help="Number of Monte Carlo samples")
parser.add_argument("--run", help="Choose which scenarios to run: 'scen', 'cf', or 'both'", 
                    type=str, choices=['scen', 'cf', 'both'], default='both')
parser.add_argument("--output_dir", type=str, default="../data/data_output/AR6_drivers", 
                    help="Directory to save concatenated files")
parser.add_argument("--override", type=bool, default=True, help="Override existing concatenated files")

if __name__ == "__main__":
    """
    Process scenario and counterfactual scenario files.
    For regular scenarios, concatenates files into a single file.
    For counterfactual scenarios, saves each category+part group as a separate file.
    """
    args = parser.parse_args()
    
    # Define output paths
    base_dir = args.output_dir
    scenario_file = os.path.join(base_dir, f"Out_scen_{args.nmc}mc.nc")
    scenario_cf_base = os.path.join(base_dir, f"Out_scen_cf_{args.nmc}mc.nc")
    
    # Create the output directory if it doesn't exist
    os.makedirs(base_dir, exist_ok=True)
    
    # Process scenario files (non-counterfactual)
    if (args.run == 'scen' or args.run == 'both') and args.override:
        print(f"Concatenating scenario files into {scenario_file}...")
        # Define the pattern based on whether we're using chunks
        pattern = f"{args.output_dir}/chunks/Out_scen_{args.nmc}mc*.nc"
        
        scenario_files = concat_multidim_files(
            pattern=pattern,
            nmc=args.nmc,
            var_keep=['D_Tg'],
            save_path=scenario_file
        )
        
        if scenario_files:
            print(f"Scenario files concatenated and saved to {scenario_files[0]}")
        else:
            print("No scenario files were found or processed")
    else:
        print(f"Concatenated scenario file already exists: {scenario_file}")
    
    # Process counterfactual scenario files
    # Since we're saving multiple files for counterfactual scenarios,
    # we don't check if a single file exists first
    if (args.run == 'cf' or args.run == 'both') and args.override:
        print(f"Processing counterfactual scenario files...")
        pattern = f"{args.output_dir}/chunks/Out_scen_cf_{args.nmc}mc*.nc"
        
        cf_files = concat_multidim_files(
            pattern=pattern,
            nmc=args.nmc,
            var_keep=['D_Tg'],
            save_path=scenario_cf_base
        )
        
        if cf_files:
            print(f"Processed {len(cf_files)} counterfactual scenario groups")
            print(f"Files are saved with the pattern: {scenario_cf_base}_category_X_partY.nc")
        else:
            print("No counterfactual scenario files were found or processed")
    
    print("Processing complete.") 