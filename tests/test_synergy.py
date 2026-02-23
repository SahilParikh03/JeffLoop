"""Tests for synergy co-occurrence matrix (Section 11)."""

from __future__ import annotations

import pytest

from src.events.limitless import DecklistEntry
from src.events.synergy import (
    SynergyTarget,
    build_cooccurrence_matrix,
    get_synergy_targets,
)


def make_decklist(*card_names: str) -> list[DecklistEntry]:
    """Helper to create a decklist from card names."""
    return [DecklistEntry(card_name=name, count=4) for name in card_names]


class TestBuildCooccurrenceMatrix:
    def test_build_matrix_single_decklist_three_cards(self) -> None:
        """3 cards in one decklist → 3 pairs (C(3,2) = 3)."""
        decklists = [make_decklist("Charizard ex", "Rare Candy", "Professor's Research")]
        matrix = build_cooccurrence_matrix(decklists)

        assert len(matrix) == 3
        # All sorted pairs should be present
        assert ("Charizard ex", "Rare Candy") in matrix
        assert ("Charizard ex", "Professor's Research") in matrix
        # "Professor's Research" < "Rare Candy" lexicographically, so sorted pair is:
        assert ("Professor's Research", "Rare Candy") in matrix

    def test_build_matrix_multiple_decklists_counts_accumulate(self) -> None:
        """Cards appearing together in multiple decklists accumulate counts."""
        dl1 = make_decklist("Charizard ex", "Rare Candy", "Arven")
        dl2 = make_decklist("Charizard ex", "Rare Candy", "Iono")
        decklists = [dl1, dl2]
        matrix = build_cooccurrence_matrix(decklists)

        # Charizard ex + Rare Candy appear together in both decklists
        assert matrix[("Charizard ex", "Rare Candy")] == 2

    def test_build_matrix_empty_returns_empty_dict(self) -> None:
        """No decklists → empty matrix."""
        matrix = build_cooccurrence_matrix([])
        assert matrix == {}

    def test_build_matrix_single_card_no_pairs(self) -> None:
        """Single card in decklist → no pairs possible."""
        decklists = [make_decklist("Charizard ex")]
        matrix = build_cooccurrence_matrix(decklists)
        assert matrix == {}

    def test_build_matrix_deduplicates_within_decklist(self) -> None:
        """Same card name appearing multiple times counts as one per decklist."""
        # DecklistEntry with same card_name but two entries
        decklist = [
            DecklistEntry(card_name="Charizard ex", count=3),
            DecklistEntry(card_name="Charizard ex", count=1),  # duplicate name
            DecklistEntry(card_name="Rare Candy", count=4),
        ]
        matrix = build_cooccurrence_matrix([decklist])

        # Should only have 1 pair, not 2
        assert len(matrix) == 1
        assert matrix[("Charizard ex", "Rare Candy")] == 1

    def test_build_matrix_keys_are_lexicographically_sorted(self) -> None:
        """Pairs are always stored with card_a < card_b lexicographically."""
        decklists = [make_decklist("Zacian V", "Arceus V")]
        matrix = build_cooccurrence_matrix(decklists)

        # "Arceus V" < "Zacian V" lexicographically
        assert ("Arceus V", "Zacian V") in matrix
        assert ("Zacian V", "Arceus V") not in matrix


class TestGetSynergyTargets:
    def _build_test_matrix(self) -> dict[tuple[str, str], int]:
        decklists = [
            make_decklist("Charizard ex", "Rare Candy", "Arven"),
            make_decklist("Charizard ex", "Rare Candy", "Iono"),
            make_decklist("Charizard ex", "Arven", "Iono"),
        ]
        return build_cooccurrence_matrix(decklists)

    def test_get_synergy_targets_finds_partners(self) -> None:
        """Finds all synergy partners for a card."""
        matrix = self._build_test_matrix()
        targets = get_synergy_targets("Charizard ex", matrix)

        partner_names = {t.card_name for t in targets}
        assert "Rare Candy" in partner_names
        assert "Arven" in partner_names
        assert "Iono" in partner_names

    def test_get_synergy_targets_top_n_respects_limit(self) -> None:
        """top_n parameter caps the result list."""
        matrix = self._build_test_matrix()
        targets = get_synergy_targets("Charizard ex", matrix, top_n=2)
        assert len(targets) <= 2

    def test_get_synergy_targets_unknown_card_returns_empty(self) -> None:
        """Unknown card returns empty list."""
        matrix = self._build_test_matrix()
        targets = get_synergy_targets("Mew ex", matrix)
        assert targets == []

    def test_synergy_targets_sorted_by_count_descending(self) -> None:
        """Results are sorted by cooccurrence_count highest first."""
        # Charizard ex + Rare Candy: 2 decklists
        # Charizard ex + Arven: 2 decklists
        # Charizard ex + Iono: 2 decklists
        # All equal here; let's build a lopsided matrix
        decklists = [
            make_decklist("Charizard ex", "Rare Candy"),  # Rare Candy count = 3
            make_decklist("Charizard ex", "Rare Candy"),
            make_decklist("Charizard ex", "Rare Candy"),
            make_decklist("Charizard ex", "Arven"),       # Arven count = 1
        ]
        matrix = build_cooccurrence_matrix(decklists)
        targets = get_synergy_targets("Charizard ex", matrix)

        assert len(targets) >= 2
        assert targets[0].card_name == "Rare Candy"
        assert targets[0].cooccurrence_count == 3
        assert targets[1].card_name == "Arven"
        assert targets[1].cooccurrence_count == 1


class TestSynergyTargetModel:
    def test_synergy_target_model_validation(self) -> None:
        """SynergyTarget validates fields correctly."""
        target = SynergyTarget(
            card_name="Rare Candy",
            card_id="SVI-191",
            cooccurrence_count=10,
        )
        assert target.card_name == "Rare Candy"
        assert target.card_id == "SVI-191"
        assert target.cooccurrence_count == 10

    def test_synergy_target_defaults(self) -> None:
        """SynergyTarget has sensible defaults."""
        target = SynergyTarget(card_name="Pikachu")
        assert target.card_id is None
        assert target.cooccurrence_count == 0
