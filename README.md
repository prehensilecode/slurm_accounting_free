# slurm_accounting_free
Computes charges from the Slurm accounting database. Includes computation of 
charges from disk usage (using `du`, `xfs_quota`, or PowerScale OneFS 
(fka Isilon) XML auto-generated reports).

## WARNING
This code almost certainly will not work without comprehensive modification
to fit your own institution’s job accounting setup. This codebase should
be used only as a reference for one possible way to do things.

