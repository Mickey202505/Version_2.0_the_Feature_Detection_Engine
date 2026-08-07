import { describe, expect, it } from "vitest";
import { GreenDetector } from "../../src/application/detectors/GreenDetector";

describe("GreenDetector", () => {
    it("returns no features for an empty detection input", () => {
        const detector = new GreenDetector();

        const result = detector.detect({
            image: {},
            metresPerPixel: 0.1
        });

        expect(result).toEqual([]);
    });
});