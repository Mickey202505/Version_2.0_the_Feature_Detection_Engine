import { describe, expect, it } from "vitest";
import {
    FeatureDetectionEngine,
    type DetectionRequest
} from "../../src";

describe("FeatureDetectionEngine", () => {
    it("can be created", () => {
        const engine = new FeatureDetectionEngine();

        expect(engine).toBeDefined();
    });

    it("returns a detection result", () => {
        const engine = new FeatureDetectionEngine();

        const request: DetectionRequest = {
            image: {},
            metresPerPixel: 0.1
        };

        const result = engine.detect(request);

        expect(result).toBeDefined();
        expect(result.features).toEqual([]);
    });
});