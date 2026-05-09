from __future__ import annotations

import argparse
import json
from argparse import Namespace
from pathlib import Path

from assess_vertical_alignment_need import compact_summary, run as run_assessment
from vertical_align_candidates import run as run_candidates


ALIGNMENT_VERDICTS = {"yes_likely", "yes_but_constrained"}


def run(args: argparse.Namespace) -> dict[str, object]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    assessment_args = Namespace(
        input=args.input,
        output_dir=str(output_dir / "assessment") if args.write_assessment_report else None,
        write_report=args.write_assessment_report,
        full_json=False,
        cell_width=args.cell_width,
        cell_height=args.cell_height,
        core_half_width=args.core_half_width,
        waist_start=args.waist_start,
        waist_end=args.waist_end,
        contact_tolerance=args.contact_tolerance,
        floor_tolerance=args.floor_tolerance,
        waist_range_threshold=args.waist_range_threshold,
        bottom_range_threshold=args.bottom_range_threshold,
        airborne_threshold=args.airborne_threshold,
    )
    assessment = run_assessment(assessment_args)
    assessment_summary = compact_summary(assessment)
    verdict = str(assessment_summary["verdict"])

    result: dict[str, object] = {
        "input": args.input,
        "output_dir": str(output_dir),
        "assessment": assessment_summary,
        "decision": "run_alignment" if verdict in ALIGNMENT_VERDICTS else "skip_alignment",
        "alignment": None,
        "confirmation_gate": {
            "required": verdict in ALIGNMENT_VERDICTS,
            "status": "pending_user_confirmation" if verdict in ALIGNMENT_VERDICTS else "not_required",
            "validation_viewer": None,
            "message": (
                "Open the validation viewer and ask the user to approve a candidate before promotion."
                if verdict in ALIGNMENT_VERDICTS
                else "Vertical alignment was not required, so no confirmation gate is needed."
            ),
        },
    }

    if verdict not in ALIGNMENT_VERDICTS:
        return result

    candidate_dir = output_dir / "alignment_candidates"
    candidate_args = Namespace(
        input=args.input,
        output_dir=str(candidate_dir),
        cell_width=args.cell_width,
        cell_height=args.cell_height,
        core_half_width=args.core_half_width,
        waist_start=args.waist_start,
        waist_end=args.waist_end,
        floor_tolerance=args.floor_tolerance,
        top_padding=args.top_padding,
        contact_baseline_tolerance=args.contact_baseline_tolerance,
        max_contact_baseline_nudge=args.max_contact_baseline_nudge,
        modes=args.candidate_modes,
        recommendation_policy=args.recommendation_policy,
    )
    candidate_report = run_candidates(candidate_args)
    validation_viewer = str(candidate_dir / "candidate_review.html")
    result["alignment"] = {
        "recommended_candidate": candidate_report.get("recommended_candidate"),
        "recommended_sheet": candidate_report.get("recommended_sheet"),
        "lowest_score_candidate": candidate_report.get("best_valid_candidate"),
        "lowest_score_sheet": candidate_report.get("best_valid_sheet"),
        "candidate_summary": str(candidate_dir / "candidate_summary.json"),
        "candidate_review": validation_viewer,
        "validation_viewer": validation_viewer,
        "recommendation_policy": args.recommendation_policy,
    }
    result["confirmation_gate"] = {
        "required": True,
        "status": "pending_user_confirmation",
        "validation_viewer": validation_viewer,
        "message": "Open the validation viewer and ask the user to approve a candidate before promotion.",
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assess a sprite sheet first, then run vertical alignment candidates only if needed."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--core-half-width", type=int, default=76)
    parser.add_argument("--waist-start", type=float, default=0.34)
    parser.add_argument("--waist-end", type=float, default=0.70)
    parser.add_argument("--contact-tolerance", type=int, default=3)
    parser.add_argument("--floor-tolerance", type=int, default=2)
    parser.add_argument("--top-padding", type=int, default=0)
    parser.add_argument("--contact-baseline-tolerance", type=int, default=4)
    parser.add_argument("--max-contact-baseline-nudge", type=int, default=4)
    parser.add_argument("--waist-range-threshold", type=int, default=8)
    parser.add_argument("--bottom-range-threshold", type=int, default=3)
    parser.add_argument("--airborne-threshold", type=int, default=12)
    parser.add_argument(
        "--candidate-modes",
        default="strict_waist,waist_floor_clamped,capped_12,capped_24,blend_50,blend_35",
    )
    parser.add_argument(
        "--recommendation-policy",
        choices=["lowest_valid", "cleanest_valid"],
        default="lowest_valid",
        help="Choose the candidate exposed as recommended when alignment runs.",
    )
    parser.add_argument(
        "--write-assessment-report",
        action="store_true",
        help="Also write the assessment HTML/images/full JSON. Alignment candidate reports are always written when alignment runs.",
    )
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
