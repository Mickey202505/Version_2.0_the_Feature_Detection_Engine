import { describe, expect, it } from "vitest";
import { DetectionPipeline } from "../../src/application/pipeline/DetectionPipeline";
import type { FeatureDetector } from "../../src/application/detectors/FeatureDetector";

describe("DetectionPipeline", () => {
    it("runs all detectors", () => {
        const detector: FeatureDetector = {
            detect: () => []
        };

        const pipeline = new DetectionPipeline([detector]);

        const result = pipeline.detect({
            image: {},
            metresPerPixel: 0.1
        });

        expect(result).toEqual([]);
    });
});