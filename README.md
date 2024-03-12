# slurm_accounting_free
Computes charges from the Slurm accounting database. Includes computation of charges from disk usage (using `du`, `xfs_quota`, or PowerScale OneFS (fka Isilon) XML auto-generated reports).

Example:
```
    sreport -p cluster AccountUtilizationByUser Account=smith Tree Start=2021-02-01 End=2021-03-01 -T billing
```
