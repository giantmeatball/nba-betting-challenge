import logging
import os

import pandas as pd

from config import STR_TODAY
from model.models.threes import ThreesModel
from model.odds_api import OddsAPI
from model.odds_api.config import OddsAPIMarkets
from model.utils.betting_math import (calc_edge_for_over_under,
                                      calc_suggested_kelly,
                                      calc_implied_probability,
                                      calc_expected_value)


class Model:

    def __init__(self, export_folder, odds_api_key, save:bool=True):
        self.export_folder = export_folder
        self.odds_api_client = OddsAPI(api_key=odds_api_key)
        self.save = save
        self.odds_df = pd.DataFrame()
        self.game_logs_df = pd.DataFrame()

    def load_data(self) -> None:
        #caching
        logging.info('Loading odds data...')
        if not os.path.exists(self.export_folder + f'/player_props/{STR_TODAY}.csv'):
            self.odds_df = self.odds_api_client.convert_player_props_to_df(
                markets=[OddsAPIMarkets.player_threes]
            )
        else:
            self.odds_df = pd.read_csv(self.export_folder + f'/player_props/{STR_TODAY}.csv')

    def save_data(self) -> None:

        #prepare folders
        logging.info('Preparing export folders...')
        if not os.path.exists(self.export_folder):
            os.mkdir(self.export_folder)

        if not os.path.exists(self.export_folder + '/player_props'):
            os.mkdir(self.export_folder + '/player_props')

        logging.info('Saving odds data to export folders...')
        #save data we loaded
        self.odds_df.to_csv(self.export_folder + f'/player_props/{STR_TODAY}.csv', index=False)

    def compress_lines(self):
        return
    
    def run_model(
            self, 
            bootstrap_samples:int=100_000,
            n_simulated_games:int=200_000,
            fga_method:str="simple",

        ):

        self.load_data()

        if self.save:
            self.save_data()

        # run models

        self.odds_df['implied_odds'] = self.odds_df['price'].apply(calc_implied_probability)

        threes_props = self.odds_df.loc[self.odds_df['prop_type'] == 'player_threes']

        threes_over_unders = threes_props.groupby('player_name', as_index=False).agg({
            'defensive_matchup': 'first',
            'points': 'first',
        })

        for idx, row in threes_over_unders.iterrows():
            player_name = row['player_name']
            defensive_matchup = row['defensive_matchup']
            points = row['points']
            try:
                simulated_fgms = ThreesModel.run_model(
                    player_name, 
                    defensive_matchup, 
                    bootstrap_samples=bootstrap_samples, 
                    n_simulated_games=n_simulated_games, 
                    fga_method="simple",
                    plot=False
                )
            except Exception as e:
                logging.error(f'Error simulating {player_name} against {defensive_matchup}: {e}')
                continue

            if not simulated_fgms.sum():
                continue

            threes_over_unders.loc[idx, 'p(over)'] = sum(simulated_fgms > points) / len(simulated_fgms)
            threes_over_unders.loc[idx, 'p(under)'] = sum(simulated_fgms < points) / len(simulated_fgms)
        
        threes_props = threes_props.merge(threes_over_unders, on=['player_name', 'defensive_matchup', 'points'], how='left')
        threes_props = threes_props.dropna() # drop players we didn't simulate
            
        threes_props['edge'] = threes_props.apply(calc_edge_for_over_under, axis=1)
        threes_props['ev'] = threes_props.apply(calc_expected_value, axis=1)
        threes_props['suggested_kelly'] = threes_props.apply(calc_suggested_kelly, axis=1)
        threes_props = threes_props.sort_values('ev', ascending=False)

        threes_props.to_csv(self.export_folder + f'/sim_results/{STR_TODAY}.csv', index=False)