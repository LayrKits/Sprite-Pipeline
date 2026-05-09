#!/usr/bin/env node

import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { createReadStream } from "node:fs";
import { copyFile, mkdir, readdir, stat, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp"]);
const MIME_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".gif", "image/gif"],
  [".html", "text/html; charset=utf-8"],
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".webp", "image/webp"]
]);

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function parseArgs(argv) {
  const options = {
    host: "127.0.0.1",
    port: 8000
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--host" && argv[index + 1]) {
      options.host = argv[index + 1];
      index += 1;
    } else if (arg === "--port" && argv[index + 1]) {
      options.port = Number(argv[index + 1]) || options.port;
      index += 1;
    }
  }
  return options;
}

function toPosix(value) {
  return value.split(path.sep).join("/");
}

function finalSpriteParts(relativePath) {
  const parts = relativePath.split("/");
  if (parts.length < 6 || parts[0] !== "Final Sprite Sheets" || parts[4] !== "sheets") {
    return {
      game: "",
      character: "",
      animation: ""
    };
  }
  return {
    game: parts[1] || "",
    character: parts[2] || "",
    animation: parts[3] || ""
  };
}

function imageSizeFromPng(buffer) {
  if (buffer.length < 24 || buffer.toString("ascii", 1, 4) !== "PNG") {
    return null;
  }
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20)
  };
}

function imageSizeFromWebp(buffer) {
  if (buffer.length < 30 || buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WEBP") {
    return null;
  }
  const chunk = buffer.toString("ascii", 12, 16);
  if (chunk === "VP8X" && buffer.length >= 30) {
    return {
      width: 1 + buffer.readUIntLE(24, 3),
      height: 1 + buffer.readUIntLE(27, 3)
    };
  }
  if (chunk === "VP8L" && buffer.length >= 25) {
    const bits = buffer.readUInt32LE(21);
    return {
      width: (bits & 0x3fff) + 1,
      height: ((bits >> 14) & 0x3fff) + 1
    };
  }
  if (chunk === "VP8 " && buffer.length >= 30) {
    return {
      width: buffer.readUInt16LE(26) & 0x3fff,
      height: buffer.readUInt16LE(28) & 0x3fff
    };
  }
  return null;
}

function imageSizeFromJpeg(buffer) {
  if (buffer.length < 4 || buffer[0] !== 0xff || buffer[1] !== 0xd8) {
    return null;
  }
  let offset = 2;
  while (offset + 9 < buffer.length) {
    if (buffer[offset] !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = buffer[offset + 1];
    const length = buffer.readUInt16BE(offset + 2);
    if (length < 2) {
      return null;
    }
    if ((marker >= 0xc0 && marker <= 0xc3) || (marker >= 0xc5 && marker <= 0xc7) || (marker >= 0xc9 && marker <= 0xcb) || (marker >= 0xcd && marker <= 0xcf)) {
      return {
        height: buffer.readUInt16BE(offset + 5),
        width: buffer.readUInt16BE(offset + 7)
      };
    }
    offset += 2 + length;
  }
  return null;
}

async function imageSize(filePath) {
  try {
    const buffer = await readFile(filePath);
    return imageSizeFromPng(buffer) || imageSizeFromWebp(buffer) || imageSizeFromJpeg(buffer) || { width: null, height: null };
  } catch {
    return { width: null, height: null };
  }
}

function layoutFromFilename(label, size) {
  const width = Number(size.width);
  const height = Number(size.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 1 || height < 1) {
    return {};
  }
  const explicit = String(label).match(/_(\d+)f_(\d+)(?:\D|$)/i);
  if (explicit) {
    const frameCount = Number(explicit[1]);
    const frameSize = Number(explicit[2]);
    if (frameCount > 0 && frameSize > 0 && width >= frameSize && height >= frameSize) {
      return {
        frameWidth: frameSize,
        frameHeight: frameSize,
        frameCount,
        rowCount: Math.max(1, Math.floor(height / frameSize))
      };
    }
  }
  if (width % 256 === 0 && height % 256 === 0) {
    return {
      frameWidth: 256,
      frameHeight: 256,
      frameCount: Math.max(1, Math.floor(width / 256)),
      rowCount: Math.max(1, Math.floor(height / 256))
    };
  }
  return {
    frameWidth: height,
    frameHeight: height,
    frameCount: Math.max(1, Math.floor(width / height)),
    rowCount: 1
  };
}

async function pathExists(filePath) {
  try {
    const fileStat = await stat(filePath);
    return fileStat.isFile();
  } catch {
    return false;
  }
}

async function readJson(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toServedUrl(relativePath) {
  return `/${toPosix(relativePath).split("/").map(encodeURIComponent).join("/")}`;
}

function timestampSlug(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
}

function safeFileSegment(value) {
  return String(value || "candidate").replace(/[^A-Za-z0-9_.-]+/g, "_");
}

function isInsideRoot(root, filePath) {
  const relative = path.relative(root, filePath);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function existingRelativePath(root, candidatePath) {
  if (!candidatePath || typeof candidatePath !== "string") {
    return "";
  }
  const filePath = path.resolve(root, candidatePath);
  if (!isInsideRoot(root, filePath) || !(await pathExists(filePath))) {
    return "";
  }
  return toPosix(path.relative(root, filePath));
}

function findKeyValue(value, keys) {
  if (!value || typeof value !== "object") {
    return "";
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findKeyValue(item, keys);
      if (found) {
        return found;
      }
    }
    return "";
  }
  for (const key of keys) {
    const current = value[key];
    if (typeof current === "string" && current) {
      return current;
    }
  }
  for (const current of Object.values(value)) {
    const found = findKeyValue(current, keys);
    if (found) {
      return found;
    }
  }
  return "";
}

function candidateReviewFromCandidatePath(candidatePath) {
  if (!candidatePath || typeof candidatePath !== "string") {
    return "";
  }
  const parts = toPosix(candidatePath).split("/");
  const index = parts.indexOf("alignment_candidates");
  if (index < 0) {
    return "";
  }
  return [...parts.slice(0, index + 1), "candidate_review.html"].join("/");
}

function tokensFor(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\.(png|webp|jpe?g|json|html)$/g, " ")
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length > 1 && token !== "256");
}

function alignmentSearchText(sheet, report, reportPath) {
  return [
    sheet.path,
    sheet.label,
    sheet.game,
    sheet.character,
    sheet.animation,
    reportPath,
    report && report.name,
    report && report.aligned_sheet,
    report && report.recommended_sheet,
    report && report.lowest_score_sheet
  ].filter(Boolean).join(" ");
}

function scoreCandidateReview(sheet, report, reportPath, review) {
  const sourceTokens = new Set(tokensFor(alignmentSearchText(sheet, report, reportPath)));
  const reviewTokens = new Set(tokensFor(review.searchText));
  let score = 0;
  for (const token of sourceTokens) {
    if (reviewTokens.has(token)) {
      score += token.length >= 4 ? 2 : 1;
    }
  }
  if (sheet.frameCount && reviewTokens.has(`${sheet.frameCount}f`)) {
    score += 4;
  }
  return score;
}

async function collectAlignmentCandidateReviews(root) {
  const searchRoots = [
    path.join(root, "isolated_workflows", "vertical_frame_alignment", "runs"),
    path.join(root, "isolated_workflows", "horizontal_frame_alignment", "runs"),
    path.join(root, "Cleanup")
  ];
  const files = [];
  for (const searchRoot of searchRoots) {
    files.push(...await walkFiles(searchRoot));
  }
  const reviews = [];
  for (const filePath of files) {
    if (path.basename(filePath) !== "candidate_review.html") {
      continue;
    }
    const relativePath = toPosix(path.relative(root, filePath));
    const fileStat = await stat(filePath);
    const summaryPath = path.join(path.dirname(filePath), "candidate_summary.json");
    const summary = await readJson(summaryPath);
    const candidateText = Array.isArray(summary && summary.candidates)
      ? summary.candidates.map((candidate) => [candidate.name, candidate.aligned_sheet].filter(Boolean).join(" ")).join(" ")
      : "";
    reviews.push({
      path: relativePath,
      modified: fileStat.mtimeMs / 1000,
      searchText: [
        relativePath,
        summary && summary.input,
        summary && summary.recommended_candidate,
        summary && summary.recommended_sheet,
        summary && summary.lowest_score_candidate,
        summary && summary.lowest_score_sheet,
        candidateText
      ].filter(Boolean).join(" ")
    });
  }
  return reviews;
}

async function candidateReviewForReport(root, sheet, report, reportPath, candidateReviews) {
  const explicit = findKeyValue(report, ["candidate_review", "validation_viewer", "review_html", "review_path", "candidateReview"]);
  const explicitPath = await existingRelativePath(root, explicit);
  if (explicitPath) {
    return explicitPath;
  }

  const candidateSheet = findKeyValue(report, ["aligned_sheet", "recommended_sheet", "lowest_score_sheet"]);
  const inferredPath = await existingRelativePath(root, candidateReviewFromCandidatePath(candidateSheet));
  if (inferredPath) {
    return inferredPath;
  }

  let best = null;
  for (const review of candidateReviews) {
    const score = scoreCandidateReview(sheet, report, reportPath, review);
    if (score > 0 && (!best || score > best.score || (score === best.score && review.modified > best.review.modified))) {
      best = { score, review };
    }
  }
  return best && best.score >= 8 ? best.review.path : "";
}

function reportMatchesAlignmentAxis(reportPath, report, axis) {
  const basename = path.basename(reportPath).toLowerCase();
  const reportAxis = String(report && report.axis ? report.axis : "").toLowerCase();
  const axisToken = axis === "horizontal" ? "horizontal" : "vertical";
  if (reportAxis.includes(axisToken)) {
    return true;
  }
  return basename.includes(axisToken) && basename.includes("alignment");
}

async function alignmentInfo(root, sheet, filePath, candidateReviews, axis) {
  const animationDir = path.dirname(path.dirname(filePath));
  const reportsDir = path.join(animationDir, "reports");
  const reportFiles = (await walkFiles(reportsDir)).filter((reportPath) => {
    return reportPath.toLowerCase().endsWith(".json") && /alignment|vertical|horizontal/.test(path.basename(reportPath).toLowerCase());
  });
  const reports = [];
  for (const reportPath of reportFiles) {
    const report = await readJson(reportPath);
    if (!report) {
      continue;
    }
    if (!reportMatchesAlignmentAxis(reportPath, report, axis)) {
      continue;
    }
    const reportStat = await stat(reportPath);
    const relativeReportPath = toPosix(path.relative(root, reportPath));
    reports.push({ report, reportPath: relativeReportPath, modified: reportStat.mtimeMs / 1000 });
  }
  reports.sort((a, b) => b.modified - a.modified || collator.compare(a.reportPath, b.reportPath));
  const selected = reports[0];
  if (!selected) {
    return null;
  }

  const candidateReviewPath = await candidateReviewForReport(root, sheet, selected.report, selected.reportPath, candidateReviews);
  const assessmentPath = await existingRelativePath(root, findKeyValue(selected.report, ["report_html", "assessment_html"]));
  return {
    ran: true,
    axis,
    reportPath: selected.reportPath,
    candidateReviewPath,
    assessmentPath,
    candidate: selected.report.name || selected.report.recommended_candidate || selected.report.method || "",
    valid: typeof selected.report.valid === "boolean" ? selected.report.valid : null,
    maxShiftPx: selected.report.max_abs_shift_px ?? selected.report.max_shift_y ?? selected.report.max_shift_x ?? null,
    floorPenetrationPx: selected.report.max_floor_penetration_px ?? null,
    canvasClipPx: selected.report.max_canvas_clip_px ?? null
  };
}

async function verticalAlignmentInfo(root, sheet, filePath, candidateReviews) {
  return alignmentInfo(root, sheet, filePath, candidateReviews, "vertical");
}

async function horizontalAlignmentInfo(root, sheet, filePath, candidateReviews) {
  return alignmentInfo(root, sheet, filePath, candidateReviews, "horizontal");
}

async function sheetRecord(root, filePath, parts, candidateReviews) {
  const extension = path.extname(filePath).toLowerCase();
  const relativePath = toPosix(path.relative(root, filePath));
  const fileStat = await stat(filePath);
  const size = await imageSize(filePath);
  const label = path.basename(filePath, extension);
  const baseRecord = {
    label,
    path: relativePath,
    folder: toPosix(path.dirname(path.relative(root, filePath))),
    ...parts,
    width: size.width,
    height: size.height,
    ...layoutFromFilename(label, size),
    bytes: fileStat.size,
    modified: fileStat.mtimeMs / 1000
  };
  const verticalAlignment = await verticalAlignmentInfo(root, baseRecord, filePath, candidateReviews);
  const horizontalAlignment = await horizontalAlignmentInfo(root, baseRecord, filePath, candidateReviews);
  return {
    ...baseRecord,
    alignment: horizontalAlignment || verticalAlignment,
    horizontalAlignment,
    verticalAlignment
  };
}

async function walkFiles(root) {
  const entries = [];
  async function visit(directory) {
    const children = await readdir(directory, { withFileTypes: true });
    children.sort((a, b) => collator.compare(a.name, b.name));
    for (const child of children) {
      const childPath = path.join(directory, child.name);
      if (child.isDirectory()) {
        await visit(childPath);
      } else if (child.isFile()) {
        entries.push(childPath);
      }
    }
  }
  try {
    await visit(root);
  } catch {
    return [];
  }
  return entries;
}

async function collectSpriteSheets(root) {
  const finalRoot = path.join(root, "Final Sprite Sheets");
  const files = await walkFiles(finalRoot);
  const candidateReviews = await collectAlignmentCandidateReviews(root);
  const sheets = [];
  for (const filePath of files) {
    const extension = path.extname(filePath).toLowerCase();
    if (!IMAGE_EXTENSIONS.has(extension)) {
      continue;
    }
    const relativePath = toPosix(path.relative(root, filePath));
    const pathParts = relativePath.split("/");
    if (!pathParts.includes("sheets") || pathParts.includes("frames")) {
      continue;
    }
    const parts = finalSpriteParts(relativePath);
    sheets.push(await sheetRecord(root, filePath, parts, candidateReviews));
  }
  sheets.sort((a, b) => {
    const modified = Number(b.modified || 0) - Number(a.modified || 0);
    return modified || collator.compare(a.path, b.path);
  });
  return sheets;
}

async function candidateSheetPath(root, summaryDir, candidate) {
  const name = String(candidate && candidate.name ? candidate.name : "");
  const alignedSheet = String(candidate && candidate.aligned_sheet ? candidate.aligned_sheet : "");
  const basename = alignedSheet ? path.basename(alignedSheet) : "";
  const localPath = basename ? path.join(summaryDir, "candidates", name, basename) : "";
  if (localPath && await pathExists(localPath)) {
    return localPath;
  }
  const rootPath = path.resolve(root, alignedSheet);
  if (isInsideRoot(root, rootPath) && await pathExists(rootPath)) {
    return rootPath;
  }
  return "";
}

function candidateWorkPaths(summaryDir, candidate, sheetPath) {
  const name = String(candidate && candidate.name ? candidate.name : "");
  const methodDir = safeFileSegment(name);
  const extension = path.extname(sheetPath) || ".png";
  const stem = path.basename(sheetPath, extension);
  const outputDir = path.join(summaryDir, "working_copies", methodDir);
  return {
    outputDir,
    workPath: path.join(outputDir, `${stem}.work${extension}`),
    offsetsPath: path.join(outputDir, `${stem}.work.offsets.json`),
    reportPath: path.join(outputDir, `${stem}.work.json`)
  };
}

async function ensureCandidateWorkCopy(root, summary, summaryDir, candidate, sheetPath) {
  const paths = candidateWorkPaths(summaryDir, candidate, sheetPath);
  const axis = String(summary && summary.axis ? summary.axis : "").toLowerCase().includes("horizontal") ? "x" : "y";
  await mkdir(paths.outputDir, { recursive: true });
  if (!(await pathExists(paths.workPath))) {
    await copyFile(sheetPath, paths.workPath);
  }
  const frameCount = Number(summary && summary.frame_count ? summary.frame_count : 0);
  let offsets = [];
  const existingOffsets = await readJson(paths.offsetsPath);
  if (existingOffsets && Array.isArray(existingOffsets.offsets) && existingOffsets.offsets.length === frameCount) {
    offsets = existingOffsets.offsets.map((value) => Math.trunc(Number(value) || 0));
  } else {
    offsets = Array(frameCount).fill(0);
    await writeFile(paths.offsetsPath, JSON.stringify({
      method: candidate.name,
      axis,
      offsets,
      source: toPosix(path.relative(root, sheetPath)),
      working_sheet: toPosix(path.relative(root, paths.workPath))
    }, null, 2));
  }
  return { ...paths, offsets };
}

async function alignmentReviewContext(root, reviewPathValue) {
  const cleanPath = decodeURIComponent(String(reviewPathValue || "")).replace(/^\/+/, "");
  const requestedPath = path.resolve(root, cleanPath);
  if (!isInsideRoot(root, requestedPath)) {
    return null;
  }

  let summaryPath = requestedPath;
  if (path.basename(requestedPath) === "candidate_review.html") {
    summaryPath = path.join(path.dirname(requestedPath), "candidate_summary.json");
  }
  if (path.basename(summaryPath) !== "candidate_summary.json") {
    return null;
  }

  const summary = await readJson(summaryPath);
  if (!summary || !Array.isArray(summary.candidates)) {
    return null;
  }

  const summaryDir = path.dirname(summaryPath);
  const summaryRel = toPosix(path.relative(root, summaryPath));
  const reviewRel = toPosix(path.relative(root, path.join(summaryDir, "candidate_review.html")));
  const candidates = [];
  for (const candidate of summary.candidates) {
    const sheetPath = await candidateSheetPath(root, summaryDir, candidate);
    if (!sheetPath) {
      continue;
    }
    const work = await ensureCandidateWorkCopy(root, summary, summaryDir, candidate, sheetPath);
    const candidateDir = path.dirname(sheetPath);
    const contactPath = path.join(candidateDir, "aligned_contact.png");
    const frameSheetPath = path.join(candidateDir, "aligned_frames.png");
    const diagnosticPath = await pathExists(contactPath)
      ? contactPath
      : await pathExists(frameSheetPath)
        ? frameSheetPath
        : "";
    const relSheet = toPosix(path.relative(root, sheetPath));
    const workRel = toPosix(path.relative(root, work.workPath));
    candidates.push({
      ...candidate,
      sheetPath,
      sheetRel: relSheet,
      sheetUrl: toServedUrl(relSheet),
      workPath: work.workPath,
      workRel,
      workUrl: toServedUrl(workRel),
      workOffsets: work.offsets,
      workReportPath: work.reportPath,
      overlayUrl: toServedUrl(path.relative(root, path.join(candidateDir, "overlay_after.png"))),
      contactUrl: diagnosticPath ? toServedUrl(path.relative(root, diagnosticPath)) : "",
      frameSheetUrl: diagnosticPath ? toServedUrl(path.relative(root, diagnosticPath)) : "",
      comparisonUrl: toServedUrl(path.relative(root, path.join(candidateDir, "comparison_before_after.png")))
    });
  }

  return {
    summary,
    summaryPath,
    summaryDir,
    summaryRel,
    reviewRel,
    candidates
  };
}

async function renderAlignmentReviewHtml(root, reviewPathValue) {
  const context = await alignmentReviewContext(root, reviewPathValue);
  if (!context || !context.candidates.length) {
    return null;
  }

  const { summary, summaryDir, reviewRel, candidates } = context;
  const axis = String(summary.axis || "").toLowerCase().includes("horizontal") ? "horizontal" : "vertical";
  const isHorizontal = axis === "horizontal";
  const recommended = String(summary.recommended_candidate || candidates[0].name || "");
  const frameCount = Number(summary.frame_count || 1);
  const cellSize = Array.isArray(summary.cell_size) ? summary.cell_size : [256, 256];
  const cellWidth = Number(cellSize[0] || 256);
  const cellHeight = Number(cellSize[1] || 256);
  const groundY = Number(summary.ground_y || 0);
  const waistY = Number(summary.target_waist_y || 0);
  const centerY = Number(summary.center_y || Math.floor(cellHeight / 2));
  const targetCoreX = Number(summary.target_core_x || Math.floor(cellWidth / 2));
  const reviewTitle = isHorizontal ? "Horizontal Alignment Candidate Review" : "Vertical Alignment Candidate Review";
  const guidePrimaryLabel = isHorizontal ? "Target core X" : "Ground Y";
  const guidePrimaryValue = isHorizontal ? targetCoreX : groundY;
  const guideSecondaryLabel = isHorizontal ? "Center Y" : "Target waist Y";
  const guideSecondaryValue = isHorizontal ? centerY : waistY;
  const overlayPath = path.join(summaryDir, "overlay_source.png");
  const sourceOverlayUrl = await pathExists(overlayPath) ? toServedUrl(path.relative(root, overlayPath)) : "";
  const methodOptions = candidates.map((candidate) => {
    const name = String(candidate.name || "");
    const selected = name === recommended ? " selected" : "";
    const label = `${name.replace(/_/g, " ")}${name === recommended ? " (recommended)" : ""}`;
    return `<option value="${escapeHtml(name)}"${selected}>${escapeHtml(label)}</option>`;
  }).join("");
  const candidateCards = candidates.map((candidate, index) => {
    const name = String(candidate.name || "");
    const status = candidate.valid ? "valid" : "invalid";
    const anchorStddev = isHorizontal ? candidate.core_x_stddev_after : candidate.waist_y_stddev_after;
    const anchorStddevLabel = isHorizontal ? "Core stddev" : "Waist stddev";
    const safetyValue = isHorizontal ? candidate.max_canvas_clip_px : candidate.max_floor_penetration_px;
    const safetyLabel = isHorizontal ? "Canvas clip" : "Floor penetration";
    const repairFrames = isHorizontal ? candidate.local_anchor_repair_frames : candidate.contact_baseline_repair_frames;
    const repairLabel = isHorizontal ? "Local fixes" : "Baseline fixes";
    const analysisLabel = isHorizontal ? "Frame analysis" : "Contact sheet";
    return `
    <section class="candidate ${status}">
      <div class="candidate-title">
        <h2>${escapeHtml(name.replace(/_/g, " "))}</h2>
        ${name === recommended ? "<span>recommended</span>" : ""}
      </div>
      <div class="metrics">
        <div><b>Status</b><span>${escapeHtml(status)}</span></div>
        <div><b>Score</b><span>${escapeHtml(candidate.score)}</span></div>
        <div><b>${anchorStddevLabel}</b><span>${escapeHtml(anchorStddev)}</span></div>
        <div><b>${safetyLabel}</b><span>${escapeHtml(safetyValue)} px</span></div>
        <div><b>${repairLabel}</b><span>${escapeHtml(Array.isArray(repairFrames) ? repairFrames.length : 0)}</span></div>
        <div><b>Max shift</b><span>${escapeHtml(candidate.max_abs_shift_px)} px</span></div>
      </div>
      <div class="candidate-media">
        <figure><figcaption>Animated candidate</figcaption><canvas class="candidate-loop" id="candidateLoop${index}" width="${cellWidth}" height="${cellHeight}"></canvas></figure>
        <figure><figcaption>Overlay</figcaption><img src="${candidate.overlayUrl}" alt="${escapeHtml(name)} overlay"></figure>
        <figure><figcaption>${analysisLabel}</figcaption>${candidate.frameSheetUrl ? `<img src="${candidate.frameSheetUrl}" alt="${escapeHtml(name)} ${analysisLabel.toLowerCase()}">` : "<p>Frame analysis not found.</p>"}</figure>
      </div>
    </section>`;
  }).join("");

  const reviewData = {
    reviewPath: reviewRel,
    axis,
    frameCount,
    cellWidth,
    cellHeight,
    centerX: Math.floor(cellWidth / 2),
    centerY,
    groundY,
    waistY,
    targetCoreX,
    recommended,
    candidates: candidates.map((candidate) => ({
      name: candidate.name,
      sheetUrl: candidate.sheetUrl,
      workUrl: candidate.workUrl,
      workOffsets: candidate.workOffsets,
      bboxes: Array.isArray(candidate.shifted_source_bboxes) ? candidate.shifted_source_bboxes : [],
      anchors: isHorizontal && Array.isArray(candidate.core_x_after) ? candidate.core_x_after : []
    }))
  };
  const reviewJson = JSON.stringify(reviewData).replace(/</g, "\\u003c");

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${reviewTitle}</title>
  <style>
    :root { color-scheme: dark; --bg: #15191e; --panel: #1c2229; --panel-2: #20262d; --line: #3a4552; --text: #eef3f8; --muted: #b8c4d2; --accent: #69c0a3; --danger: #d87575; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); }
    a { color: inherit; }
    button, input, select { font: inherit; }
    .nav { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 12px; min-height: 58px; padding: 10px 18px; background: #20262d; border-bottom: 1px solid var(--line); }
    .nav h1 { margin: 0; font-size: 16px; line-height: 1.2; }
    .nav a { flex: 0 0 auto; padding: 8px 11px; border: 1px solid var(--line); border-radius: 6px; text-decoration: none; color: var(--text); background: #2a3139; }
    main { max-width: 1420px; margin: 0 auto; padding: 22px; display: grid; gap: 18px; }
    p { color: var(--muted); line-height: 1.5; margin: 0; }
    .top { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
    .top div, .metrics div, .editor { background: var(--panel-2); border: 1px solid var(--line); border-radius: 6px; padding: 12px; }
    b { display: block; color: #94a3b8; font-size: 12px; text-transform: uppercase; }
    span { display: block; margin-top: 4px; }
    .source-review { display: grid; grid-template-columns: minmax(280px, .55fr) minmax(420px, 1fr); gap: 16px; align-items: start; }
    figure { margin: 0; }
    figcaption { color: #cbd5e1; font-size: 13px; margin-bottom: 8px; }
    img, canvas { display: block; max-width: 100%; background: #101419; border: 1px solid #39434f; border-radius: 4px; }
    canvas { image-rendering: pixelated; }
    .editor { display: grid; gap: 12px; }
    .editor-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .editor-header h2 { margin: 0; font-size: 16px; }
    .editor-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
    .editor-grid { display: grid; grid-template-columns: minmax(256px, 320px) minmax(220px, 1fr); gap: 14px; align-items: start; }
    .editor-stack { display: grid; gap: 12px; }
    .editor-row label { display: inline-flex; align-items: center; gap: 7px; color: #d8e2ec; }
    .editor-row label span { display: inline; margin-top: 0; }
    select, input { border: 1px solid #516171; border-radius: 5px; color: var(--text); background: #11161c; padding: 6px 7px; }
    input[type="number"] { width: 58px; }
    .icon-button { min-width: 38px; height: 36px; display: inline-grid; place-items: center; border: 1px solid #516171; border-radius: 6px; color: var(--text); background: #303842; cursor: pointer; }
    .icon-button.primary { color: #10231d; background: var(--accent); border-color: var(--accent); font-weight: 750; }
    .icon-button.secondary { min-width: 132px; }
    .icon-button.auto { min-width: 204px; }
    .icon-button.finalize { min-width: 92px; background: #e9b75f; border-color: #e9b75f; color: #21180a; font-weight: 750; }
    .status { min-height: 20px; color: var(--muted); font-size: 13px; }
    .candidate { padding: 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }
    .candidate.valid { border-color: #4fb58f; }
    .candidate.invalid { border-color: #b75b5b; }
    .candidate-title { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
    .candidate-title h2 { margin: 0; font-size: 16px; text-transform: capitalize; }
    .candidate-title span { margin: 0; padding: 3px 7px; border: 1px solid color-mix(in srgb, var(--accent), transparent 25%); border-radius: 999px; color: #dff8ef; background: rgba(105, 192, 163, .13); font-size: 12px; font-weight: 650; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 14px; }
    .candidate-media { display: grid; grid-template-columns: minmax(256px, 320px) minmax(0, .75fr) minmax(0, 1.25fr); gap: 16px; align-items: start; }
    .candidate-loop { width: 256px; height: 256px; }
    @media (max-width: 1120px) { .source-review, .candidate-media, .editor-grid { grid-template-columns: 1fr; } .nav { align-items: flex-start; } }
  </style>
</head>
<body>
  <nav class="nav">
    <a href="/sprite_viewer.html">Back to viewer</a>
    <h1>${reviewTitle}</h1>
  </nav>
  <main>
    <p><b>Confirmation required:</b> pick a candidate and note any fixes before promotion.</p>
    <div class="top">
      <div><b>Recommended</b><span>${escapeHtml(summary.recommended_candidate)}</span></div>
      <div><b>Lowest score</b><span>${escapeHtml(summary.best_valid_candidate)}</span></div>
      <div><b>${guidePrimaryLabel}</b><span>${escapeHtml(guidePrimaryValue)}</span></div>
      <div><b>${guideSecondaryLabel}</b><span>${escapeHtml(guideSecondaryValue)}</span></div>
      <div><b>Frames</b><span>${escapeHtml(frameCount)}</span></div>
    </div>
    <section class="source-review">
      <figure>
        <figcaption>Original copied sheet overlay</figcaption>
        ${sourceOverlayUrl ? `<img src="${sourceOverlayUrl}" alt="Original copied sheet overlay">` : "<p>Source overlay not found.</p>"}
      </figure>
      <section class="editor" aria-label="Manual frame review">
        <div class="editor-header">
          <h2>Working Copy</h2>
          <label for="methodSelect">Method <select id="methodSelect">${methodOptions}</select></label>
        </div>
        <div class="editor-grid">
          <figure>
            <figcaption>Editable working sheet with guide lines</figcaption>
            <canvas id="frameCanvas" width="${cellWidth}" height="${cellHeight}"></canvas>
          </figure>
          <div class="editor-stack">
            <div class="editor-row">
              <button class="icon-button primary" id="workPlay" type="button">Play</button>
              <button class="icon-button" id="prevFrame" type="button">&lt;&lt;</button>
              <label for="frameInput"><input id="frameInput" type="number" min="1" max="${frameCount}" value="1"> <span>of ${frameCount}</span></label>
              <button class="icon-button" id="nextFrame" type="button">&gt;&gt;</button>
            </div>
            <div class="editor-row">
              <button class="icon-button" id="nudgeNegative" type="button" title="${isHorizontal ? "Move frame left 1px" : "Move frame up 1px"}">${isHorizontal ? "←" : "↑"}</button>
              <button class="icon-button" id="nudgePositive" type="button" title="${isHorizontal ? "Move frame right 1px" : "Move frame down 1px"}">${isHorizontal ? "→" : "↓"}</button>
              <button class="icon-button secondary auto" id="autoCleanup" type="button">Attempt automatic cleanup</button>
              <button class="icon-button primary" id="saveAdjustments" type="button">Save</button>
              <button class="icon-button secondary" id="restoreCandidate" type="button">Restore from candidate</button>
              <button class="icon-button finalize" id="finalizeWork" type="button">Finalize</button>
            </div>
            <p>Save updates the working copy only. Restore resets it from the immutable candidate. Finalize opens the working copy in the viewer.</p>
            <div class="status" id="editorStatus"></div>
          </div>
        </div>
      </section>
    </section>
    ${candidateCards}
  </main>
  <script>
    const review = ${reviewJson};
    const methodSelect = document.getElementById('methodSelect');
    const frameInput = document.getElementById('frameInput');
    const frameCanvas = document.getElementById('frameCanvas');
    const frameContext = frameCanvas.getContext('2d');
    const editorStatus = document.getElementById('editorStatus');
    const workPlay = document.getElementById('workPlay');
    const candidateImages = new Map();
    const workImages = new Map();
    const offsets = Object.fromEntries(review.candidates.map((candidate) => [
      candidate.name,
      Array.isArray(candidate.workOffsets) && candidate.workOffsets.length === review.frameCount
        ? candidate.workOffsets.map((value) => Math.trunc(Number(value) || 0))
        : Array(review.frameCount).fill(0)
    ]));
    let frameIndex = 0;
    let candidateLoopFrame = 0;
    let candidateLoopTimer = 0;
    let workPlaying = false;
    let workTimer = 0;

    function selectedCandidate() {
      return review.candidates.find((candidate) => candidate.name === methodSelect.value) || review.candidates[0];
    }
    function clamp(value, low, high) {
      return Math.max(low, Math.min(high, value));
    }
    function checker(ctx) {
      const size = 16;
      for (let y = 0; y < review.cellHeight; y += size) {
        for (let x = 0; x < review.cellWidth; x += size) {
          ctx.fillStyle = ((x / size + y / size) % 2) ? '#2b3037' : '#22262b';
          ctx.fillRect(x, y, size, size);
        }
      }
    }
    function guide(ctx, x1, y1, x2, y2, color) {
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x1 + 0.5, y1 + 0.5);
      ctx.lineTo(x2 + 0.5, y2 + 0.5);
      ctx.stroke();
      ctx.restore();
    }
    function drawGuides(ctx, axisGuide) {
      guide(ctx, review.centerX, 0, review.centerX, review.cellHeight - 1, 'rgb(80, 218, 255)');
      if (review.axis === 'horizontal') {
        guide(ctx, 0, review.centerY, review.cellWidth - 1, review.centerY, 'rgb(255, 118, 118)');
        guide(ctx, review.targetCoreX, 0, review.targetCoreX, review.cellHeight - 1, 'rgb(255, 218, 72)');
        if (Number.isFinite(axisGuide)) {
          guide(ctx, axisGuide, 0, axisGuide, review.cellHeight - 1, 'rgb(255, 0, 255)');
        }
        return;
      }
      guide(ctx, 0, review.groundY, review.cellWidth - 1, review.groundY, 'rgb(255, 92, 92)');
      guide(ctx, 0, review.waistY, review.cellWidth - 1, review.waistY, 'rgb(255, 218, 72)');
      if (Number.isFinite(axisGuide)) {
        guide(ctx, 0, axisGuide, review.cellWidth - 1, axisGuide, 'rgb(255, 0, 255)');
      }
    }
    function axisGuideFor(candidate, index, offset) {
      const bbox = Array.isArray(candidate.bboxes[index]) ? candidate.bboxes[index] : null;
      if (review.axis === 'horizontal') {
        if (Array.isArray(candidate.anchors) && Number.isFinite(Number(candidate.anchors[index]))) {
          return Number(candidate.anchors[index]) + offset;
        }
        return bbox ? ((Number(bbox[0]) + Number(bbox[2])) / 2) + offset : null;
      }
      return bbox ? Number(bbox[3]) + offset : null;
    }
    function drawSheetFrame(ctx, image, candidate, index, offset = 0) {
      checker(ctx);
      const dx = review.axis === 'horizontal' ? offset : 0;
      const dy = review.axis === 'horizontal' ? 0 : offset;
      if (image && image.complete && image.naturalWidth) {
        ctx.drawImage(image, index * review.cellWidth, 0, review.cellWidth, review.cellHeight, dx, dy, review.cellWidth, review.cellHeight);
      }
      drawGuides(ctx, axisGuideFor(candidate, index, offset));
    }
    function drawCandidateLoops() {
      for (const [index, candidate] of review.candidates.entries()) {
        const canvas = document.getElementById('candidateLoop' + index);
        if (!canvas) {
          continue;
        }
        const context = canvas.getContext('2d');
        drawSheetFrame(context, candidateImages.get(candidate.name), candidate, candidateLoopFrame, 0);
      }
    }
    function tickCandidateLoops() {
      candidateLoopFrame = (candidateLoopFrame + 1) % review.frameCount;
      drawCandidateLoops();
      candidateLoopTimer = window.setTimeout(tickCandidateLoops, 1000 / 12);
    }
    function drawFrame() {
      const candidate = selectedCandidate();
      const image = candidateImages.get(candidate.name);
      const offset = offsets[candidate.name][frameIndex] || 0;
      drawSheetFrame(frameContext, image, candidate, frameIndex, offset);
      frameInput.value = String(frameIndex + 1);
      const label = review.axis === 'horizontal' ? 'dx' : 'dy';
      editorStatus.textContent = candidate.name.replaceAll('_', ' ') + ' frame ' + (frameIndex + 1) + ' ' + label + ' ' + offset + 'px';
    }
    function setFrame(nextFrame) {
      frameIndex = Math.max(0, Math.min(review.frameCount - 1, nextFrame));
      drawFrame();
    }
    function nudge(amount) {
      const candidate = selectedCandidate();
      offsets[candidate.name][frameIndex] = (offsets[candidate.name][frameIndex] || 0) + amount;
      drawFrame();
    }
    function setWorkPlaying(nextPlaying) {
      workPlaying = nextPlaying;
      workPlay.textContent = workPlaying ? 'Pause' : 'Play';
      if (workTimer) {
        window.clearTimeout(workTimer);
        workTimer = 0;
      }
      if (workPlaying) {
        tickWork();
      }
    }
    function tickWork() {
      if (!workPlaying) {
        return;
      }
      setFrame((frameIndex + 1) % review.frameCount);
      workTimer = window.setTimeout(tickWork, 1000 / 12);
    }
    function replaceWorkImage(candidate, src) {
      const image = new Image();
      image.src = src;
      workImages.set(candidate.name, image);
    }
    function automaticOffsets(candidate) {
      const nextOffsets = [];
      let aligned = 0;
      let clampedFrames = 0;
      let missingFrames = 0;
      for (let index = 0; index < review.frameCount; index += 1) {
        const bbox = Array.isArray(candidate.bboxes[index]) ? candidate.bboxes[index] : null;
        if (!bbox) {
          nextOffsets.push(0);
          missingFrames += 1;
          continue;
        }
        let desired;
        let minOffset;
        let maxOffset;
        if (review.axis === 'horizontal') {
          const left = Math.trunc(Number(bbox[0]) || 0);
          const right = Math.trunc(Number(bbox[2]) || 0);
          const anchor = Array.isArray(candidate.anchors) && Number.isFinite(Number(candidate.anchors[index]))
            ? Number(candidate.anchors[index])
            : (left + right) / 2;
          desired = Math.trunc(review.targetCoreX - anchor);
          minOffset = -left;
          maxOffset = review.cellWidth - right;
        } else {
          const top = Math.trunc(Number(bbox[1]) || 0);
          const bottom = Math.trunc(Number(bbox[3]) || 0);
          desired = Math.trunc(review.groundY - bottom);
          minOffset = -top;
          maxOffset = review.cellHeight - bottom;
        }
        const offset = clamp(desired, minOffset, maxOffset);
        nextOffsets.push(offset);
        if (offset === desired) {
          aligned += 1;
        } else {
          clampedFrames += 1;
        }
      }
      return { offsets: nextOffsets, aligned, clampedFrames, missingFrames };
    }
    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error || 'Request failed.');
      }
      return body;
    }
    async function saveAdjustments(silent = false) {
      const candidate = selectedCandidate();
      if (!silent) {
        editorStatus.textContent = 'Saving working copy...';
      }
      const payload = await postJson('/api/alignment-review/save', {
        reviewPath: review.reviewPath,
        method: candidate.name,
        offsets: offsets[candidate.name]
      });
      replaceWorkImage(candidate, payload.workSheetUrl || payload.savedSheetUrl);
      if (!silent) {
        editorStatus.innerHTML = 'Saved working copy <a href="' + (payload.workSheetUrl || payload.savedSheetUrl) + '">' + payload.workSheet + '</a>';
      }
      return payload;
    }
    async function attemptAutomaticCleanup() {
      const candidate = selectedCandidate();
      const result = automaticOffsets(candidate);
      setWorkPlaying(false);
      offsets[candidate.name] = result.offsets;
      frameIndex = 0;
      drawFrame();
      editorStatus.textContent = 'Saving automatic cleanup to working copy...';
      const payload = await saveAdjustments(true);
      const notes = [];
      if (result.clampedFrames) {
        notes.push(result.clampedFrames + ' clamped');
      }
      if (result.missingFrames) {
        notes.push(result.missingFrames + ' missing bounds');
      }
      const suffix = notes.length ? ' (' + notes.join(', ') + ')' : '';
      const targetLabel = review.axis === 'horizontal' ? 'core line' : 'ground line';
      editorStatus.innerHTML = 'Automatic cleanup saved: ' + result.aligned + ' frames aligned to ' + targetLabel + suffix + '. <a href="' + (payload.workSheetUrl || payload.savedSheetUrl) + '">Working copy</a>';
    }
    async function restoreFromCandidate() {
      const candidate = selectedCandidate();
      editorStatus.textContent = 'Restoring working copy...';
      const payload = await postJson('/api/alignment-review/restore', {
        reviewPath: review.reviewPath,
        method: candidate.name
      });
      offsets[candidate.name] = payload.offsets;
      replaceWorkImage(candidate, payload.workSheetUrl);
      editorStatus.textContent = 'Restored working copy from candidate.';
      drawFrame();
    }
    async function finalizeWork() {
      const candidate = selectedCandidate();
      editorStatus.textContent = 'Finalizing working copy...';
      await saveAdjustments(true);
      const payload = await postJson('/api/alignment-review/finalize', {
        reviewPath: review.reviewPath,
        method: candidate.name
      });
      window.location.href = payload.viewerUrl;
    }
    for (const candidate of review.candidates) {
      const candidateImage = new Image();
      candidateImage.src = candidate.sheetUrl;
      candidateImage.addEventListener('load', () => {
        drawCandidateLoops();
        drawFrame();
      });
      candidateImages.set(candidate.name, candidateImage);
      const workImage = new Image();
      workImage.src = candidate.workUrl;
      workImages.set(candidate.name, workImage);
    }
    methodSelect.addEventListener('change', drawFrame);
    frameInput.addEventListener('change', () => setFrame(Number.parseInt(frameInput.value, 10) - 1 || 0));
    workPlay.addEventListener('click', () => setWorkPlaying(!workPlaying));
    document.getElementById('prevFrame').addEventListener('click', () => setFrame(frameIndex - 1));
    document.getElementById('nextFrame').addEventListener('click', () => setFrame(frameIndex + 1));
    document.getElementById('nudgeNegative').addEventListener('click', () => nudge(-1));
    document.getElementById('nudgePositive').addEventListener('click', () => nudge(1));
    document.getElementById('autoCleanup').addEventListener('click', () => attemptAutomaticCleanup().catch((error) => { editorStatus.textContent = error.message; }));
    document.getElementById('saveAdjustments').addEventListener('click', () => saveAdjustments().catch((error) => { editorStatus.textContent = error.message; }));
    document.getElementById('restoreCandidate').addEventListener('click', () => restoreFromCandidate().catch((error) => { editorStatus.textContent = error.message; }));
    document.getElementById('finalizeWork').addEventListener('click', () => finalizeWork().catch((error) => { editorStatus.textContent = error.message; }));
    drawFrame();
    drawCandidateLoops();
    tickCandidateLoops();
  </script>
</body>
</html>`;
}

async function readRequestJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 2_000_000) {
      throw new Error("Request body is too large.");
    }
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

function runCommand(command, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(stderr || stdout || `Command exited with ${code}`));
      }
    });
  });
}

async function saveAlignmentReviewAdjustments(root, body) {
  const context = await alignmentReviewContext(root, body && body.reviewPath);
  if (!context) {
    return { status: 404, payload: { error: "Candidate review not found." } };
  }
  const method = String(body && body.method ? body.method : "");
  const candidate = context.candidates.find((item) => item.name === method);
  if (!candidate) {
    return { status: 400, payload: { error: "Unknown alignment method." } };
  }
  const offsets = Array.isArray(body && body.offsets) ? body.offsets.map((value) => Math.trunc(Number(value) || 0)) : [];
  const frameCount = Number(context.summary.frame_count || 0);
  if (offsets.length !== frameCount) {
    return { status: 400, payload: { error: "Offset count does not match frame count." } };
  }

  const work = candidateWorkPaths(context.summaryDir, candidate, candidate.sheetPath);
  const axis = String(context.summary && context.summary.axis ? context.summary.axis : "").toLowerCase().includes("horizontal") ? "x" : "y";
  await mkdir(work.outputDir, { recursive: true });
  await writeFile(work.offsetsPath, JSON.stringify({
    method,
    axis,
    offsets,
    source: toPosix(path.relative(root, candidate.sheetPath)),
    working_sheet: toPosix(path.relative(root, work.workPath)),
    updated_at: new Date().toISOString()
  }, null, 2));

  const pythonPath = await pathExists(path.join(root, ".venv", "bin", "python"))
    ? path.join(root, ".venv", "bin", "python")
    : "python3";
  const workflowDir = axis === "x" ? "horizontal_frame_alignment" : "vertical_frame_alignment";
  const scriptPath = path.join(root, "isolated_workflows", workflowDir, "apply_manual_candidate_offsets.py");
  await runCommand(pythonPath, [
    scriptPath,
    "--input", candidate.sheetPath,
    "--offsets-json", work.offsetsPath,
    "--output", work.workPath,
    "--report", work.reportPath,
    "--cell-width", String((context.summary.cell_size && context.summary.cell_size[0]) || 256),
    "--cell-height", String((context.summary.cell_size && context.summary.cell_size[1]) || 256)
  ], root);

  const savedSheet = toPosix(path.relative(root, work.workPath));
  const savedReport = toPosix(path.relative(root, work.reportPath));
  const version = Date.now();
  return {
    status: 200,
    payload: {
      savedSheet,
      savedReport,
      workSheet: savedSheet,
      workSheetUrl: `${toServedUrl(savedSheet)}?v=${version}`,
      savedSheetUrl: `${toServedUrl(savedSheet)}?v=${version}`,
      savedReportUrl: toServedUrl(savedReport)
    }
  };
}

async function restoreAlignmentReviewWorkCopy(root, body) {
  const context = await alignmentReviewContext(root, body && body.reviewPath);
  if (!context) {
    return { status: 404, payload: { error: "Candidate review not found." } };
  }
  const method = String(body && body.method ? body.method : "");
  const candidate = context.candidates.find((item) => item.name === method);
  if (!candidate) {
    return { status: 400, payload: { error: "Unknown alignment method." } };
  }
  const work = candidateWorkPaths(context.summaryDir, candidate, candidate.sheetPath);
  const axis = String(context.summary && context.summary.axis ? context.summary.axis : "").toLowerCase().includes("horizontal") ? "x" : "y";
  await mkdir(work.outputDir, { recursive: true });
  await copyFile(candidate.sheetPath, work.workPath);
  const offsets = Array(Number(context.summary.frame_count || 0)).fill(0);
  await writeFile(work.offsetsPath, JSON.stringify({
    method,
    axis,
    offsets,
    source: toPosix(path.relative(root, candidate.sheetPath)),
    working_sheet: toPosix(path.relative(root, work.workPath)),
    restored_at: new Date().toISOString()
  }, null, 2));
  const workSheet = toPosix(path.relative(root, work.workPath));
  return {
    status: 200,
    payload: {
      offsets,
      workSheet,
      workSheetUrl: `${toServedUrl(workSheet)}?v=${Date.now()}`
    }
  };
}

async function finalizeAlignmentReviewWorkCopy(root, body) {
  const context = await alignmentReviewContext(root, body && body.reviewPath);
  if (!context) {
    return { status: 404, payload: { error: "Candidate review not found." } };
  }
  const method = String(body && body.method ? body.method : "");
  const candidate = context.candidates.find((item) => item.name === method);
  if (!candidate) {
    return { status: 400, payload: { error: "Unknown alignment method." } };
  }
  const work = candidateWorkPaths(context.summaryDir, candidate, candidate.sheetPath);
  if (!(await pathExists(work.workPath))) {
    await copyFile(candidate.sheetPath, work.workPath);
  }
  const workSheet = toPosix(path.relative(root, work.workPath));
  return {
    status: 200,
    payload: {
      workSheet,
      workSheetUrl: toServedUrl(workSheet),
      viewerUrl: `/sprite_viewer.html?sheet=${encodeURIComponent(workSheet)}`
    }
  };
}

function sendJson(response, statusCode, payload) {
  const body = Buffer.from(JSON.stringify(payload, null, 2));
  response.writeHead(statusCode, {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length
  });
  response.end(body);
}

function sendText(response, statusCode, text) {
  const body = Buffer.from(text);
  response.writeHead(statusCode, {
    "Cache-Control": "no-store",
    "Content-Type": "text/plain; charset=utf-8",
    "Content-Length": body.length
  });
  response.end(body);
}

function sendHtml(response, statusCode, html) {
  const body = Buffer.from(html);
  response.writeHead(statusCode, {
    "Cache-Control": "no-store",
    "Content-Type": "text/html; charset=utf-8",
    "Content-Length": body.length
  });
  response.end(body);
}

function serveFile(response, root, requestPath) {
  const decoded = decodeURIComponent(requestPath);
  const relative = decoded === "/" ? "sprite_viewer.html" : decoded.replace(/^\/+/, "");
  const filePath = path.resolve(root, relative);
  if (!filePath.startsWith(root + path.sep) && filePath !== root) {
    sendText(response, 403, "Forbidden");
    return;
  }
  const extension = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES.get(extension) || "application/octet-stream";
  stat(filePath)
    .then((fileStat) => {
      if (!fileStat.isFile()) {
        sendText(response, 404, "Not found");
        return;
      }
      response.writeHead(200, {
        "Cache-Control": "no-store",
        "Content-Type": contentType,
        "Content-Length": fileStat.size
      });
      createReadStream(filePath).pipe(response);
    })
    .catch(() => sendText(response, 404, "Not found"));
}

async function handleRequest(request, response, root) {
  const url = new URL(request.url || "/", "http://viewer.local");
  if (request.method === "GET" && url.pathname === "/alignment-review") {
    const html = await renderAlignmentReviewHtml(root, url.searchParams.get("path"));
    if (!html) {
      sendText(response, 404, "Alignment candidate review not found.");
      return;
    }
    sendHtml(response, 200, html);
    return;
  }
  if (url.pathname === "/api/sprite-sheets") {
    sendJson(response, 200, { sheets: await collectSpriteSheets(root) });
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/alignment-review/save") {
    const result = await saveAlignmentReviewAdjustments(root, await readRequestJson(request));
    sendJson(response, result.status, result.payload);
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/alignment-review/restore") {
    const result = await restoreAlignmentReviewWorkCopy(root, await readRequestJson(request));
    sendJson(response, result.status, result.payload);
    return;
  }
  if (request.method === "POST" && url.pathname === "/api/alignment-review/finalize") {
    const result = await finalizeAlignmentReviewWorkCopy(root, await readRequestJson(request));
    sendJson(response, result.status, result.payload);
    return;
  }
  serveFile(response, root, url.pathname);
}

const scriptPath = fileURLToPath(import.meta.url);
const root = path.dirname(path.dirname(scriptPath));
const options = parseArgs(process.argv.slice(2));
const server = createServer((request, response) => {
  handleRequest(request, response, root).catch(() => {
    sendJson(response, 500, { error: "Could not handle request." });
  });
});

server.listen(options.port, options.host, () => {
  const url = `http://${options.host}:${options.port}/sprite_viewer.html`;
  console.log(`Serving sprite viewer at ${url}`);
  console.log("Use Re-load local structure to scan Final Sprite Sheets without reloading the page.");
});
