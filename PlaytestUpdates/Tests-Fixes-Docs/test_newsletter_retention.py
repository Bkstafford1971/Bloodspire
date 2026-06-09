import os
import random
import tempfile
import unittest

import save
from team import create_ai_team
from matchmaking import run_turn


class NewsletterRetentionTest(unittest.TestCase):
    def setUp(self):
        # Redirect saves into a temporary directory for safe isolated testing.
        self.tempdir = tempfile.TemporaryDirectory()
        self.orig = {
            'SAVES_DIR': save.SAVES_DIR,
            'TEAMS_DIR': save.TEAMS_DIR,
            'FIGHTS_DIR': save.FIGHTS_DIR,
            'LOGS_DIR': save.LOGS_DIR,
            'GRAVEYARD_DIR': save.GRAVEYARD_DIR,
            'GAME_STATE_FILE': save.GAME_STATE_FILE,
            'NEWSLETTERS_DIR': save.NEWSLETTERS_DIR,
            'CHAMPION_FILE': save.CHAMPION_FILE,
        }
        save.SAVES_DIR = self.tempdir.name
        save.TEAMS_DIR = os.path.join(save.SAVES_DIR, 'teams')
        save.FIGHTS_DIR = os.path.join(save.SAVES_DIR, 'fights')
        save.LOGS_DIR = os.path.join(save.SAVES_DIR, 'logs')
        save.GRAVEYARD_DIR = os.path.join(save.SAVES_DIR, 'graveyard')
        save.GAME_STATE_FILE = os.path.join(save.SAVES_DIR, 'game_state.json')
        save.NEWSLETTERS_DIR = os.path.join(save.SAVES_DIR, 'newsletters')
        save.CHAMPION_FILE = os.path.join(save.SAVES_DIR, 'champion.json')
        save._ensure_dirs()
        save.save_game_state({
            'next_team_id': 1,
            'next_fight_id': 1,
            'turn_number': 1,
        })

    def tearDown(self):
        for key, value in self.orig.items():
            setattr(save, key, value)
        self.tempdir.cleanup()

    def test_opponent_team_activity_is_saved_for_newsletter_retention(self):
        random.seed(0)

        player_team = create_ai_team(team_name='Player Team', manager_name='Player Manager')
        opponent_team = create_ai_team(team_name='Opponent Team', manager_name='Opponent Manager')

        card = run_turn(player_team, [opponent_team], verbose=False, champion_state={})
        self.assertTrue(card, 'Expected at least one fight in the turn card')

        opponent_team_id = opponent_team.team_id
        self.assertGreater(opponent_team_id, 0, 'Opponent team should have been assigned an ID')

        loaded_opponent = save.load_team(opponent_team_id)
        self.assertEqual(loaded_opponent.last_turn_ran, 1,
                         'Opponent team should record the last active turn')
        self.assertTrue(any(entry.get('turn') == 1 for entry in loaded_opponent.turn_history),
                        'Opponent team turn_history should include the current turn')

        team_file = os.path.join(save.TEAMS_DIR, f'team_{opponent_team_id:04d}.json')
        self.assertTrue(os.path.exists(team_file), 'Opponent team save file should exist')


if __name__ == '__main__':
    unittest.main()
