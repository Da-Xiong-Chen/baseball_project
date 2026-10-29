"""Legacy same-name labels resolve only through the player's dated evidence."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import player_input

class PlayerInputTests(unittest.TestCase):
    def test_legacy_suffix_does_not_depend_on_the_other_players_future_debut(self):
        rows=pd.DataFrame([dict(name='rebas:CPBL:gdEku',raw_name='林子崴',team='統一7-ELEVEn獅',role='P',date=pd.Timestamp('2024-04-01'))])
        with patch.object(player_input,'resolve_identity',side_effect=ValueError('not unique')),patch.object(player_input,'load',return_value=(None,None,rows)):
            self.assertEqual(player_input.resolve_player('林子崴〔統一〕','2024-04-02','統一7-ELEVEn獅','P'),'rebas:CPBL:gdEku')
            for args in [('2024-04-01','統一7-ELEVEn獅','P'),('2024-04-02','樂天桃猿','P'),('2024-04-02','統一7-ELEVEn獅','B')]:
                with self.assertRaises(ValueError):player_input.resolve_player('林子崴〔統一〕',*args)
            with self.assertRaises(ValueError):player_input.resolve_player('林子崴〔樂天〕','2024-04-02','統一7-ELEVEn獅','P')

if __name__=='__main__':unittest.main()
