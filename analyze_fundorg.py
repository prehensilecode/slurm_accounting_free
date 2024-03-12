#!/usr/bin/env python3
import sys
import os
import pandas as pd
import numpy as np
import datetime

pd.set_option('display.max_columns', None)

def main():
    fundorg_df = pd.read_csv('fundorg_codes.csv')

    valid_fundorg_df = fundorg_df[(fundorg_df['Fund-Org code'].str.match(pat=r'\d{6}\D\d{4}'))]
    print('Valid fundorg')
    print(valid_fundorg_df)
    print()

    charges_df = pd.read_csv('myorg_charges_202301.csv')
    # print(charges_df[(charges_df['Fund-Org code'] != 'xxxxxx-xxxx')])

    nonzero_charges_df = charges_df[(charges_df['Fund-Org code'] != 'xxxxxx-xxxx') & (charges_df['Total charge ($)'] > 0.)].copy(deep=True)
    nonzero_charges_df.reset_index(inplace=True, drop=True)

    print('Valid fundorg and non-zero charges')
    print(nonzero_charges_df[['Fund-Org code', 'Last name', 'First name', 'Project', 'Total charge ($)']])
    print(len(nonzero_charges_df.index))

    print('Only those receiving monthly credit:')
    mask = nonzero_charges_df['Monthly credit?'] == True
    nonzero_charges_df.loc[mask, 'Total charge ($)'] = nonzero_charges_df['Total charge ($)'] - 100.
    nonzero_charges_df = nonzero_charges_df[nonzero_charges_df['Total charge ($)'] > 0.].copy(deep=True).reset_index()
    nonzero_charges_df = nonzero_charges_df[['Fund-Org code', 'Last name', 'First name', 'Project', 'Total charge ($)']].copy(deep=True)
    nonzero_charges_df.reset_index(inplace=True, drop=True)
    print(nonzero_charges_df)
    print(len(nonzero_charges_df.index))

    # XXX for some reason, one row gets the "-" substituted by an en-dash
    # workaround is to split on non-numeric
    fundorg_split_series = nonzero_charges_df['Fund-Org code'].str.split(r'\D', regex=True)
    print(f'type(fundorg_split_series) = {type(fundorg_split_series)}')
    fundorg_df = pd.DataFrame(fundorg_split_series.tolist(), columns=['Fund', 'Orgn'])
    print(fundorg_df)
    print(len(fundorg_df.index))


    d = datetime.date(2023, 1, 1)
    month_str = d.strftime('%b')
    year_str = d.strftime('%Y')

    nonzero_charges_df[['Fund', 'Orgn']] = fundorg_df
    nonzero_charges_df['Account'] = 4120
    nonzero_charges_df['Program'] = ''
    nonzero_charges_df['Activity'] = ''
    nonzero_charges_df['Location'] = ''
    nonzero_charges_df['Debit'] = nonzero_charges_df['Total charge ($)']
    nonzero_charges_df['Credit'] = np.NaN
    nonzero_charges_df['Description (35 Characters maximum)'] = nonzero_charges_df["First name"].astype(str) + ' ' + nonzero_charges_df["Last name"].astype(str) + ' ' + month_str + ' ' + year_str
    nonzero_charges_df['Description (35 Characters maximum)'] = nonzero_charges_df['Description (35 Characters maximum)'].str[:35]

    short_year_str = year_str[2:]
    nonzero_charges_df['Reference ID'] = f'URCF{d.month:02d}{short_year_str}'
    nonzero_charges_df.reset_index(inplace=True, drop=True)

    desc_sr = f"{nonzero_charges_df['First name']} {nonzero_charges_df['Last name']} {month_str} {year_str}"
    print('desc_sr = ')
    print(desc_sr)

    print()

    nonzero_charges_df = nonzero_charges_df[['Fund', 'Orgn', 'Account', 'Program', 'Activity', 'Location', 'Debit', 'Credit', 'Description (35 Characters maximum)', 'Reference ID']].copy(deep=True)
    nonzero_charges_df.reset_index(inplace=True, drop=True)

    # Create the credits
    credits_df = pd.DataFrame().reindex_like(nonzero_charges_df)
    credits_df['Credit'] = nonzero_charges_df['Debit']
    credits_df['Fund'] = 196750
    credits_df['Orgn'] = 3018
    credits_df['Account'] = 8010
    credits_df['Description (35 Characters maximum)'] = nonzero_charges_df['Description (35 Characters maximum)']
    credits_df['Reference ID'] = 'URCF0123'

    banner_charges_df = pd.concat([nonzero_charges_df, credits_df])
    banner_charges_df.reset_index(inplace=True, drop=True)
    print(banner_charges_df)

    banner_charges_df[['Fund', 'Orgn', 'Account', 'Program', 'Activity', 'Location', 'Debit', 'Credit', 'Description (35 Characters maximum)', 'Reference ID']].to_csv('foobar.csv', float_format='%.2f', index=False)


if __name__ == '__main__':
    main()

