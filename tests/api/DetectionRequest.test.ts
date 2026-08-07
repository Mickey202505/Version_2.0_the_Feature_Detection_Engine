import { describe, expect, it } from "vitest";
import type { DetectionRequest } from "../../src/api/DetectionRequest";

describe("DetectionRequest", () => {
    it("can represent an image detection request", () => {
        const request: DetectionRequest = {
            image: {},
            metresPerPixel: 0.1
        };

        expect(request.metresPerPixel).toBe(0.1);
    });
});