import polars as pl
import duckdb
import dotenv
import os
dotenv.load_dotenv(override=True)


con = duckdb.connect()
con.execute("""
INSTALL ducklake; LOAD 'ducklake';
""")
con.execute(os.getenv("DUCKLAKE_CONFIG"))


prefix = '../data/data_output/AR6_drivers/dtg_weighted_'
temper_hist = (
    pl.scan_parquet(f'{prefix}' + 'hist_2000mc.parquet')
    .with_columns(model=pl.lit('historical'),strategy=pl.lit('historical'))
    .rename({'scen':'scenario'})
    .select(pl.col('category', 'model', 'scenario','strategy','measure','year','value'))
)

temper_scen = (
    pl.scan_parquet(f'{prefix}' + 'scen_2000mc.parquet')
    .with_columns(strategy=pl.lit('ideal'))
    .with_columns(scen=pl.col('scen').str.splitn('|',2).struct.rename_fields(['model','scenario']))
    .unnest('scen')
    .select(pl.col('category','model','scenario','strategy','measure','year','value'))
)
temper_cf = (
    pl.scan_parquet(f'{prefix}' + 'cf_2000mc*_scen_all.parquet')
    .with_columns(scen=pl.col('scen').str.splitn('|',3).struct.rename_fields(['model','scenario','strategy']))
    .unnest('scen')
    .select(pl.col('category','model','scenario','strategy','measure','year','value'))
)

temper = pl.concat([temper_hist, temper_scen, temper_cf]).collect()
con.execute("""create or replace table MIRACLE_MAIN.temper as select * from temper""")
print('Exported to ducklake')
