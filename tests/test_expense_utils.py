"""Tests for expense archive scanning utilities."""

import pytest
from pathlib import Path
from import_.expense_utils import (
    extract_date_from_filename,
    scan_archive,
    FOLDER_TO_CATEGORIE,
)
from components.archive_paths import ARCHIVE_BASE




class TestExtractDateMMYY:
    """Pattern: MMYY_description.pdf (most common in 2025)."""

    def test_january_2025(self):
        assert extract_date_from_filename('0125_KPN Mobiel.pdf', 2025) == '2025-01-01'

    def test_december_2025(self):
        assert extract_date_from_filename('1225_KPN Thuis.pdf', 2025) == '2025-12-01'

    def test_june_2025(self):
        assert extract_date_from_filename('0625_Glucosemeter.pdf', 2025) == '2025-06-01'

    def test_with_dash_separator(self):
        assert extract_date_from_filename('0125-KPN.pdf', 2025) == '2025-01-01'

    def test_mmyy_wrong_year_returns_none(self):
        """0124 in 2025 folder — YY=24 doesn't match 2025, not MMYY."""
        assert extract_date_from_filename('0124_Something.pdf', 2025) is None

    def test_mmyy_2024(self):
        """In 2024 folder, 0524 = May 2024."""
        assert extract_date_from_filename('0524_KPN.pdf', 2024) == '2024-05-01'


class TestExtractDateYYMM:
    """Pattern: YYMM_description.pdf (e.g. Pensioenpremie files)."""

    def test_january_2025(self):
        assert extract_date_from_filename('2501_Pensioenpremie.pdf', 2025) == '2025-01-01'

    def test_december_2025(self):
        assert extract_date_from_filename('2512_Pensioenpremie.pdf', 2025) == '2025-12-01'

    def test_yymm_wrong_year_returns_none(self):
        """2401 in 2025 folder — YY=24 doesn't match."""
        assert extract_date_from_filename('2401_Something.pdf', 2025) is None


class TestExtractDateMMUnderscoreYY:
    """Pattern: MM_YY_description.pdf (common in 2023/2024)."""

    def test_underscore_separator(self):
        assert extract_date_from_filename('05_23_financielejaarstukken.pdf', 2023) == '2023-05-01'

    def test_dash_separator(self):
        assert extract_date_from_filename('01-24_Boekhouder_Administratie_Jaarstukken.pdf', 2024) == '2024-01-01'

    def test_december(self):
        assert extract_date_from_filename('12_23_boekhouder_schadeverzekering.pdf', 2023) == '2023-12-01'

    def test_mm_yy_2025(self):
        assert extract_date_from_filename('05_25_NHG_Contributie.pdf', 2025) == '2025-05-01'


class TestExtractDateMMDDYY:
    """Pattern: MMDDYY_description.pdf (6 digits)."""

    def test_december_31_2025(self):
        assert extract_date_from_filename('123125_Wijgergangs_Dermatoscoop.pdf', 2025) == '2025-12-31'

    def test_january_15_2026(self):
        assert extract_date_from_filename('011526_Something.pdf', 2026) == '2026-01-15'


class TestExtractDateISOFormat:
    """Pattern: YYYY-MM-DD_description.pdf."""

    def test_iso_date(self):
        assert extract_date_from_filename('2024-02-29_Boekhouder-Schadeverzekerigen.pdf', 2024) == '2024-02-29'

    def test_iso_date_2025(self):
        assert extract_date_from_filename('2025-01-03_kpn.pdf', 2025) == '2025-01-03'


class TestExtractDateNoDate:
    """Files with no recognizable date pattern."""

    def test_no_date_text_only(self):
        assert extract_date_from_filename('Boekhouder_Factuur.pdf', 2025) is None

    def test_no_date_long_number(self):
        """Invoice number, not a date."""
        assert extract_date_from_filename('92790289764.pdf', 2025) is None

    def test_no_date_invoice_number_4digit(self):
        """0647 doesn't match MMYY (47!=25) or YYMM (06!=25)."""
        assert extract_date_from_filename('0647_Amac.pdf', 2025) is None

    def test_no_date_another_invoice_number(self):
        assert extract_date_from_filename('0697_skge.pdf', 2025) is None

    def test_no_date_prefixed_text(self):
        assert extract_date_from_filename('Moneybird_01_25__Factuur.pdf', 2025) is None

    def test_no_date_factuur_prefix(self):
        assert extract_date_from_filename('Factuur_122725_AppleCareVerzekering.pdf', 2025) is None

    def test_no_date_abonnement(self):
        assert extract_date_from_filename('Abonnementsfactuur 24053198.pdf', 2025) is None

    def test_invalid_month_13(self):
        """Month 13 is invalid."""
        assert extract_date_from_filename('1325_Something.pdf', 2025) is None

    def test_two_digit_year_only(self):
        """'25_Boekhouder-Verzekering-1.pdf' — just YY, no month. Not a valid pattern."""
        assert extract_date_from_filename('25_Boekhouder-Verzekering-1.pdf', 2025) is None

    def test_pensioen_prefix(self):
        """'pensioen_01_24_Factuur.pdf' — date is after text prefix."""
        assert extract_date_from_filename('pensioen_01_24_Factuur.pdf', 2024) is None


class TestExtractDateEdgeCases:
    """Edge cases and boundary conditions."""

    def test_month_boundaries(self):
        for month in range(1, 13):
            result = extract_date_from_filename(f'{month:02d}25_test.pdf', 2025)
            assert result == f'2025-{month:02d}-01', f'Failed for month {month}'

    def test_yymm_month_boundaries(self):
        for month in range(1, 13):
            result = extract_date_from_filename(f'25{month:02d}_test.pdf', 2025)
            assert result == f'2025-{month:02d}-01', f'Failed for YYMM month {month}'

    def test_year_2023(self):
        assert extract_date_from_filename('0623_test.pdf', 2023) == '2023-06-01'

    def test_year_2026(self):
        assert extract_date_from_filename('0326_test.pdf', 2026) == '2026-03-01'

    def test_ambiguous_mmyy_yymm_same_result(self):
        """When MMYY and YYMM would give same result (e.g. '2525'), MMYY wins.
        But month 25 is invalid, so YYMM should be tried."""
        # Actually 2525: MMYY → month=25 invalid. YYMM → month=25 invalid. None.
        assert extract_date_from_filename('2525_test.pdf', 2025) is None

    def test_mmyy_ambiguous_but_mmyy_valid(self):
        """0125 in 2025: MMYY gives month=01 (valid), YYMM gives month=25 (invalid).
        Should return MMYY result."""
        assert extract_date_from_filename('0125_test.pdf', 2025) == '2025-01-01'

    def test_yymm_only_valid(self):
        """2501 in 2025: MMYY gives YY=01 (!=25, skip), YYMM gives month=01 (valid)."""
        assert extract_date_from_filename('2501_test.pdf', 2025) == '2025-01-01'




class TestRealFilenames2025:
    """Test against actual filenames from the 2025 archive."""

    def test_kpn_mobiel(self):
        assert extract_date_from_filename('0125_KPN Mobiel.pdf', 2025) == '2025-01-01'

    def test_administratie_boekhouder(self):
        assert extract_date_from_filename('0825_Administratie en jaarstukken_Boekhouder.pdf', 2025) == '2025-08-01'

    def test_pensioenpremie(self):
        assert extract_date_from_filename('2501_Pensioenpremie.pdf', 2025) == '2025-01-01'

    def test_pensioenpremie_december(self):
        assert extract_date_from_filename('2512_Pensioenpremie.pdf', 2025) == '2025-12-01'

    def test_nhg_contributie(self):
        assert extract_date_from_filename('05_25_NHG_Contributie.pdf', 2025) == '2025-05-01'

    def test_glucosemeter(self):
        assert extract_date_from_filename('0625_Glucosemeter.pdf', 2025) == '2025-06-01'

    def test_amac_invoice_number(self):
        """0647 is an invoice number, not a date."""
        assert extract_date_from_filename('0647_Amac.pdf', 2025) is None

    def test_wijgergangs_dermatoscoop(self):
        assert extract_date_from_filename('123125_Wijgergangs_Dermatoscoop.pdf', 2025) == '2025-12-31'

    def test_moneybird_no_date(self):
        """Date embedded after text prefix — not detected."""
        assert extract_date_from_filename('Moneybird_02_25_Factuur.pdf', 2025) is None

    def test_boekhouder_verzekering_year_only(self):
        """Just '25_' prefix — not enough for a date."""
        assert extract_date_from_filename('25_Boekhouder-Verzekering-1.pdf', 2025) is None

    def test_aov_zorgservice(self):
        assert extract_date_from_filename('0125_AOV zorgservice.pdf', 2025) == '2025-01-01'


class TestRealFilenames2024:
    """Test against actual filenames from the 2024 archive."""

    def test_mm_yy_underscore(self):
        assert extract_date_from_filename('01_24_Mobieletelefoon.pdf', 2024) == '2024-01-01'

    def test_mm_yy_dash(self):
        assert extract_date_from_filename('01-24_Boekhouder_Administratie_Jaarstukken.pdf', 2024) == '2024-01-01'

    def test_iso_date(self):
        assert extract_date_from_filename('2024-02-29_Boekhouder-Schadeverzekerigen.pdf', 2024) == '2024-02-29'

    def test_pensioen_prefix_no_date(self):
        assert extract_date_from_filename('pensioen_01_24_Factuur.pdf', 2024) is None

    def test_kpn_internet_no_date(self):
        assert extract_date_from_filename('KPN_Internet_Factuur_9702.pdf', 2024) is None

    def test_no_date_text(self):
        assert extract_date_from_filename('Microsoft office 365.pdf', 2024) is None


class TestRealFilenames2023:
    """Test against actual filenames from the 2023 archive."""

    def test_mm_yy_underscore(self):
        assert extract_date_from_filename('05_23_financielejaarstukken.pdf', 2023) == '2023-05-01'

    def test_mm_yy_underscore_verzekering(self):
        assert extract_date_from_filename('12_23_boekhouder_schadeverzekering.pdf', 2023) == '2023-12-01'




class TestFolderMapping:
    def test_all_known_folders_mapped(self):
        """All folders from the archive should have a mapping."""
        known_folders = [
            'Accountancy', 'Software', 'Pensioenpremie', 'Verzekeringen',
            'KPN', 'Kleine_Aankopen', 'Lidmaatschappen', 'Investeringen',
            'Representatie', 'Scholingskosten',
        ]
        for folder in known_folders:
            assert folder in FOLDER_TO_CATEGORIE, f'{folder} not mapped'

    def test_software_maps_to_accountancy(self):
        assert FOLDER_TO_CATEGORIE['Software'] == 'Accountancy/software'

    def test_accountancy_maps_to_accountancy(self):
        assert FOLDER_TO_CATEGORIE['Accountancy'] == 'Accountancy/software'

    def test_kleine_aankopen_underscore(self):
        assert FOLDER_TO_CATEGORIE['Kleine_Aankopen'] == 'Kleine aankopen'

    def test_kpn_maps_to_telefoon(self):
        assert FOLDER_TO_CATEGORIE['KPN'] == 'Telefoon/KPN'

    def test_pensioenpremie_maps_to_sph(self):
        assert FOLDER_TO_CATEGORIE['Pensioenpremie'] == 'Pensioenpremie SPH'

    def test_aov_not_mapped(self):
        """AoV is NOT a business expense, should not be in mapping."""
        assert 'AoV' not in FOLDER_TO_CATEGORIE

    def test_all_categories_valid(self):
        """All mapped categories must be in KOSTEN_CATEGORIEEN."""
        from components.utils import KOSTEN_CATEGORIEEN
        for folder, cat in FOLDER_TO_CATEGORIE.items():
            assert cat in KOSTEN_CATEGORIEEN, f'{folder} → {cat} not in KOSTEN_CATEGORIEEN'




archive_2025_exists = (ARCHIVE_BASE / '2025' / 'Uitgaven').exists()
archive_2024_exists = (ARCHIVE_BASE / '2024' / 'Uitgaven').exists()


class TestScanArchive:
    def test_scan_nonexistent_year(self):
        """Scanning a non-existent year returns empty list."""
        result = scan_archive(1999)
        assert result == []

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_2025_finds_pdfs(self):
        """2025 archive should have many PDFs."""
        results = scan_archive(2025)
        assert len(results) > 50

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_returns_required_keys(self):
        """Each result dict should have all required keys."""
        results = scan_archive(2025)
        assert len(results) > 0
        required_keys = {'path', 'filename', 'folder', 'categorie', 'datum', 'already_imported'}
        for item in results:
            assert required_keys.issubset(item.keys()), f'Missing keys in {item}'

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_path_is_pathlib(self):
        results = scan_archive(2025)
        assert all(isinstance(r['path'], Path) for r in results)

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_categories_valid(self):
        """All returned categories must be in KOSTEN_CATEGORIEEN."""
        from components.utils import KOSTEN_CATEGORIEEN
        results = scan_archive(2025)
        for item in results:
            assert item['categorie'] in KOSTEN_CATEGORIEEN, (
                f"Unknown category: {item['categorie']} for {item['filename']}"
            )

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_skips_aov_folder(self):
        """AoV folder should not produce results (not mapped)."""
        # 2026 has an AoV folder
        results_2026 = scan_archive(2026)
        aov_items = [r for r in results_2026 if r['folder'] == 'AoV']
        assert len(aov_items) == 0

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_all_filenames_end_pdf(self):
        results = scan_archive(2025)
        for item in results:
            assert item['filename'].lower().endswith('.pdf')

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_no_dedup_by_default(self):
        """Without existing_filenames, nothing should be marked imported."""
        results = scan_archive(2025)
        for item in results:
            assert item['already_imported'] is False

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_dedup_exact_filename(self):
        """Exact filename match should mark as already imported."""
        results = scan_archive(2025, existing_filenames={'0125_KPN Mobiel.pdf'})
        kpn_items = [r for r in results if r['filename'] == '0125_KPN Mobiel.pdf']
        assert len(kpn_items) == 1
        assert kpn_items[0]['already_imported'] is True

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_dedup_in_path(self):
        """Filename embedded in a full path should also match."""
        results = scan_archive(
            2025,
            existing_filenames={'data/uitgaven/0125_KPN Mobiel.pdf'},
        )
        kpn_items = [r for r in results if r['filename'] == '0125_KPN Mobiel.pdf']
        assert len(kpn_items) == 1
        assert kpn_items[0]['already_imported'] is True

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_dedup_non_matching(self):
        """Non-matching existing filenames should leave items as not imported."""
        results = scan_archive(2025, existing_filenames={'totally_unrelated.pdf'})
        assert all(r['already_imported'] is False for r in results)

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_dates_extracted_for_known_files(self):
        """Spot-check that specific files get correct dates."""
        results = scan_archive(2025)
        by_name = {r['filename']: r for r in results}

        if '0125_KPN Mobiel.pdf' in by_name:
            assert by_name['0125_KPN Mobiel.pdf']['datum'] == '2025-01-01'
        if '2501_Pensioenpremie.pdf' in by_name:
            assert by_name['2501_Pensioenpremie.pdf']['datum'] == '2025-01-01'

    @pytest.mark.skipif(not archive_2025_exists, reason='2025 archive not available')
    def test_scan_folders_in_results(self):
        """Results should include files from multiple folders."""
        results = scan_archive(2025)
        folders = {r['folder'] for r in results}
        assert 'KPN' in folders
        assert 'Verzekeringen' in folders

    @pytest.mark.skipif(not archive_2024_exists, reason='2024 archive not available')
    def test_scan_2024(self):
        """2024 archive should also work."""
        results = scan_archive(2024)
        assert len(results) > 30

    @pytest.mark.skipif(not archive_2024_exists, reason='2024 archive not available')
    def test_scan_2024_representatie_folder(self):
        """2024 has a Representatie folder."""
        results = scan_archive(2024)
        folders = {r['folder'] for r in results}
        assert 'Representatie' in folders
