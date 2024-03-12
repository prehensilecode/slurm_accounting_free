#!/usr/bin/env python3
import sys
import os
import csv
import delorean

# For accounts without a fund-org code (i.e. code is "000000-0000" or
# "xxxxxx-xxxx" set a grpTRESMins=billing=487805
#     sacctmgr modify account somethingPrj grptresmins=billing=487805

def main():
    grptresmins = 487805
    # Classes get 5000 cpu-days per term. 10 weeks per term, 4 weeks per month
    # => 5000/2.5*60*24 cpu-minutes per month = 2880000 = 2.88e6
    classtresmins = int(2.88e6)
    fundorg_fn = '/ifs/sysadmin/RCM/fundorg_codes.csv'
    with open(fundorg_fn, 'r') as fundorg_csv:
        reader = csv.DictReader(fundorg_csv)
        for row in reader:
            if row['Fund-Org code'] == 'xxxxxx-xxxx' or row['Fund-Org code'] == '000000-0000':
                if row['MRI?'] == 'TRUE':
                    print(f"MRI Project={row['Project']} Code={row['Fund-Org code']}")

                    # check expiration
                    now = delorean.now()
                    expiry = delorean.parse(row['Share expiration'])
                    if now >= expiry:
                        print('Expired grant')
                        print(f"sacctmgr modify account {row['Project']} set grptresmins=billing={grptresmins:d}")
                    print('')
                elif row['Class?'] == 'TRUE':
                    print(f"CLASS Project={row['Project']} Code={row['Fund-Org code']}")
                    print(f"sacctmgr modify account {row['Project']} set grptresmins=billing={classtresmins:d}")
                    print('')
                elif row['Startup/Grant?'] == 'TRUE':
                    print(f"STARTUP Project={row['Project']} Code={row['Fund-Org code']}")

                    # check expiration
                    now = delorean.now()
                    expiry = delorean.parse(row['Share expiration'])
                    if now >= expiry:
                        print('Expired grant')
                        print(f"sacctmgr modify account {row['Project']} set grptresmins=billing={grptresmins:d}")
                    print('')
                else:
                    print(f"NOT FUNDED Project={row['Project']} Code={row['Fund-Org code']}")
                    print(f"sacctmgr modify account {row['Project']} set grptresmins=billing={grptresmins:d}")
                    print('')
            else:
                print(f"FUNDED Project={row['Project']} Code={row['Fund-Org code']}")
                print('')


if __name__ == '__main__':
    main()

