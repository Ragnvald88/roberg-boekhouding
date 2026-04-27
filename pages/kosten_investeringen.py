# pages/kosten_investeringen.py
"""Activastaat UI — lifted from pages/kosten.py.

Kept as a separate module so the main Kosten page body stays focused on
the bank-tx reconciliation view. Behavior is unchanged from the prior
inline implementation.
"""
from nicegui import ui

from components.utils import format_euro
from database import (
    DB_PATH,
    YearLockedError,
    get_fiscale_params,
    get_investeringen_voor_afschrijving,
    get_afschrijving_overrides,
    get_afschrijving_overrides_batch,
    set_afschrijving_override,
    delete_afschrijving_override,
    update_uitgave,
)
from fiscal.afschrijvingen import bereken_afschrijving


async def _is_jaar_definitief(db_path, jaar: int) -> bool:
    """Lane 5 (review A7) — return True if `jaar` has
    jaarafsluiting_status='definitief'. Pure helper so it can be unit-tested
    without spinning up a NiceGUI runtime.
    """
    params = await get_fiscale_params(db_path, jaar)
    if params is None:
        return False
    return getattr(params, 'jaarafsluiting_status', 'concept') == 'definitief'


LEVENSDUUR_OPTIES = {3: "3 jaar", 4: "4 jaar", 5: "5 jaar"}


async def laad_activastaat(container, jaar: int, on_change) -> None:
    """Render the activastaat card into `container`. `on_change` is an async
    callable invoked after edits so the caller can refresh dependent UI.

    L8/U4 (codex follow-up): the lock-state for the displayed jaar is now
    computed BEFORE the table renders, so the user sees a banner up-front
    and the per-row "tune" button is suppressed (instead of letting the
    user click through into a dialog that quietly disables every year's
    input). The dialog still does its own per-year locked_years lookup
    when it opens, which remains the source of truth for save-side
    rejection.
    """
    container.clear()
    investeringen = await get_investeringen_voor_afschrijving(
        DB_PATH, tot_jaar=jaar)
    if not investeringen:
        with container:
            ui.label("Geen investeringen in dit jaar of daarvoor.") \
                .classes("text-grey")
        return

    # Compute the lock-state for the current jaar BEFORE rendering. This
    # drives both the banner and the per-row action visibility below.
    is_jaar_locked = await _is_jaar_definitief(DB_PATH, jaar)

    all_overrides = await get_afschrijving_overrides_batch(
        DB_PATH, [u.id for u in investeringen])

    with container:
        ui.label(f"Activastaat per 31-12-{jaar}") \
            .classes("text-subtitle1 text-bold")
        if is_jaar_locked:
            ui.label(
                f"Jaar {jaar} is definitief afgesloten. "
                "Heropen via Jaarafsluiting voor correcties."
            ).classes("text-caption text-warning q-mt-xs")
        activa_rows = []
        for u in investeringen:
            aanschaf = (u.aanschaf_bedrag or u.bedrag) * (
                (u.zakelijk_pct if u.zakelijk_pct is not None else 100) / 100)
            result = bereken_afschrijving(
                aanschaf_bedrag=aanschaf,
                restwaarde_pct=u.restwaarde_pct or 10,
                levensduur=u.levensduur_jaren or 5,
                aanschaf_maand=int(u.datum[5:7]),
                aanschaf_jaar=int(u.datum[0:4]),
                bereken_jaar=jaar,
                overrides=all_overrides.get(u.id),
            )
            activa_rows.append({
                "id": u.id,
                "omschrijving": u.omschrijving,
                "aanschaf": format_euro(aanschaf),
                "afschr_dit_jaar": format_euro(result["afschrijving"]),
                "boekwaarde": format_euro(result["boekwaarde"]),
                "has_override": result.get("has_override", False),
                "_aanschaf_bedrag": aanschaf,
                "_restwaarde_pct": u.restwaarde_pct or 10,
                "_levensduur": u.levensduur_jaren or 5,
                "_aanschaf_maand": int(u.datum[5:7]),
                "_aanschaf_jaar": int(u.datum[0:4]),
            })

        columns = [
            {"name": "omschrijving", "label": "Omschrijving",
             "field": "omschrijving", "align": "left"},
            {"name": "aanschaf", "label": "Aanschaf (zakelijk)",
             "field": "aanschaf", "align": "right"},
            {"name": "afschr_dit_jaar", "label": f"Afschr {jaar}",
             "field": "afschr_dit_jaar", "align": "right"},
            {"name": "boekwaarde", "label": "Boekwaarde",
             "field": "boekwaarde", "align": "right"},
            {"name": "acties", "label": "", "field": "acties",
             "align": "center"},
        ]
        activa_tbl = ui.table(columns=columns, rows=activa_rows,
                              row_key="id") \
            .classes("w-full").props("dense flat")
        activa_tbl.add_slot("body-cell-afschr_dit_jaar", '''
            <q-td :props="props">
                <span>{{ props.row.afschr_dit_jaar }}</span>
                <q-icon v-if="props.row.has_override" name="edit"
                        size="xs" color="primary" class="q-ml-xs" />
            </q-td>
        ''')
        # L8/U4: when the displayed jaar is definitief, render the tune
        # button as disabled. The dialog itself still checks locked_years
        # per-row, so this is purely a UX hint — clicking would only
        # surface a fully-disabled schedule anyway.
        disable_attr = ' disable' if is_jaar_locked else ''
        activa_tbl.add_slot("body-cell-acties", f'''
            <q-td :props="props">
                <q-btn flat dense icon="tune" size="sm"
                       color="primary" title="Afschrijving aanpassen"{disable_attr}
                       @click="$parent.$emit('edit_afschr', props.row)" />
            </q-td>
        ''')
        activa_tbl.on(
            "edit_afschr",
            lambda e: open_afschrijving_dialog(e.args, jaar, on_change))


async def open_afschrijving_dialog(row: dict, huidige_jaar: int,
                                    on_change) -> None:
    """Open the per-year override dialog. `on_change` is called after save."""
    uitgave_id = row["id"]
    aanschaf = row["_aanschaf_bedrag"]
    restwaarde_pct = row["_restwaarde_pct"]
    levensduur_state = {"value": row["_levensduur"]}
    aanschaf_maand = row["_aanschaf_maand"]
    aanschaf_jaar = row["_aanschaf_jaar"]

    overrides = await get_afschrijving_overrides(DB_PATH, uitgave_id)

    # Lane 5 (review A7): lock per-year inputs based on
    # jaarafsluiting_status='definitief' instead of the prior
    # `y < huidige_jaar` heuristic. Pre-fetch the status for every year
    # the dialog might render so we don't await inside build_schedule.
    laatste_jaar_max = aanschaf_jaar + max(LEVENSDUUR_OPTIES.keys())
    toon_tot_max = max(laatste_jaar_max, huidige_jaar)
    locked_years: dict[int, bool] = {}
    for _y in range(aanschaf_jaar, toon_tot_max + 1):
        locked_years[_y] = await _is_jaar_definitief(DB_PATH, _y)

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl q-pa-md"):
        ui.label(f'Afschrijving — {row["omschrijving"]}') \
            .classes("text-h6 q-mb-sm")

        with ui.row().classes("w-full items-end gap-4"):
            ui.label(f"Aanschaf: {format_euro(aanschaf)}") \
                .classes("text-caption text-grey")
            ui.label(f"Restwaarde: {restwaarde_pct:.0f}%") \
                .classes("text-caption text-grey")
            levensduur_input = ui.select(
                LEVENSDUUR_OPTIES, label="Levensduur",
                value=levensduur_state["value"]).classes("w-28")

        ui.separator().classes("q-my-sm")

        schedule_container = ui.column().classes("w-full gap-0")
        inputs_by_year: dict[int, ui.number | None] = {}

        def build_schedule():
            schedule_container.clear()
            inputs_by_year.clear()
            lv = levensduur_state["value"]
            laatste_jaar = aanschaf_jaar + lv
            toon_tot = max(laatste_jaar, huidige_jaar)

            with schedule_container:
                with ui.row().classes("w-full items-center gap-2 q-pb-xs") \
                        .style("border-bottom: 1px solid #E2E8F0"):
                    ui.label("Jaar") \
                        .classes("text-caption text-bold") \
                        .style("width: 60px")
                    ui.label("Berekend") \
                        .classes("text-caption text-bold text-right") \
                        .style("width: 90px")
                    ui.label("Handmatig") \
                        .classes("text-caption text-bold") \
                        .style("width: 120px")
                    ui.label("Boekwaarde") \
                        .classes("text-caption text-bold text-right") \
                        .style("width: 90px")

                for y in range(aanschaf_jaar, toon_tot + 1):
                    auto = bereken_afschrijving(
                        aanschaf_bedrag=aanschaf,
                        restwaarde_pct=restwaarde_pct,
                        levensduur=lv,
                        aanschaf_maand=aanschaf_maand,
                        aanschaf_jaar=aanschaf_jaar,
                        bereken_jaar=y)
                    auto_val = auto["afschrijving"]

                    result_with = bereken_afschrijving(
                        aanschaf_bedrag=aanschaf,
                        restwaarde_pct=restwaarde_pct,
                        levensduur=lv,
                        aanschaf_maand=aanschaf_maand,
                        aanschaf_jaar=aanschaf_jaar,
                        bereken_jaar=y,
                        overrides=overrides)

                    has_ov = y in overrides
                    override_val = overrides.get(y)
                    # Lane 5 (review A7): UI lock is the
                    # jaarafsluiting_status, not a year-cutoff.
                    is_locked = locked_years.get(y, False)

                    with ui.row().classes(
                            "w-full items-center gap-2 q-py-xs") \
                            .style("border-bottom: 1px solid #F1F5F9"):
                        lbl = ui.label(str(y)).style("width: 60px")
                        if y == huidige_jaar:
                            lbl.classes("text-bold text-primary")
                        else:
                            lbl.classes("text-caption")

                        ui.label(format_euro(auto_val)) \
                            .classes("text-caption text-grey text-right") \
                            .style("width: 90px")

                        if is_locked:
                            if has_ov:
                                ui.label(format_euro(override_val)) \
                                    .classes("text-caption text-bold") \
                                    .style("width: 120px")
                            else:
                                ui.label("—") \
                                    .classes("text-caption text-grey") \
                                    .style("width: 120px")
                            inputs_by_year[y] = None
                        else:
                            inp = ui.number(
                                value=override_val if has_ov else None,
                                format="%.2f", min=0, step=0.01,
                                placeholder=f"{auto_val:.2f}") \
                                .classes("w-28") \
                                .props("dense outlined hide-bottom-space")
                            inputs_by_year[y] = inp

                        bw_label = ui.label(
                            format_euro(result_with["boekwaarde"])) \
                            .classes("text-caption text-right") \
                            .style("width: 90px")
                        if has_ov:
                            bw_label.classes("text-bold")

                if any(locked_years.get(y, False)
                       for y in range(aanschaf_jaar, toon_tot + 1)):
                    ui.label(
                        "Definitief afgesloten jaren zijn vergrendeld. "
                        "Heropen via Jaarafsluiting voor correcties.") \
                        .classes("text-caption text-grey q-mt-sm")

        def on_levensduur_change():
            levensduur_state["value"] = levensduur_input.value
            build_schedule()

        levensduur_input.on(
            "update:model-value", lambda: on_levensduur_change())
        build_schedule()

        with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
            ui.button("Annuleren", on_click=dialog.close).props("flat")

            async def opslaan():
                new_lv = levensduur_state["value"]
                # Lane 5 (review A7/A13): the underlying DB helpers
                # raise YearLockedError when one of the touched years is
                # definitief. Catch + notify so the user sees a Dutch
                # warning instead of an unhandled background traceback.
                try:
                    if new_lv != row["_levensduur"]:
                        await update_uitgave(
                            DB_PATH, uitgave_id=uitgave_id,
                            levensduur_jaren=new_lv)
                    for y, inp in inputs_by_year.items():
                        if inp is None:
                            continue
                        val = inp.value
                        if val is not None and val >= 0:
                            await set_afschrijving_override(
                                DB_PATH, uitgave_id, y, val)
                            overrides[y] = val
                        elif y in overrides:
                            await delete_afschrijving_override(
                                DB_PATH, uitgave_id, y)
                            del overrides[y]
                except YearLockedError as ex:
                    ui.notify(str(ex), type='warning', position='top')
                    return
                dialog.close()
                ui.notify("Afschrijvingen opgeslagen", type="positive")
                await on_change()

            ui.button("Opslaan", icon="save",
                      on_click=opslaan).props("color=primary")

    dialog.open()
