import { describe, expect, it } from "vitest";
import { WorldPoint } from "../../src/domain/WorldPoint";

describe("WorldPoint", () => {
    it("stores world X and Y coordinates", () => {
        const point = new WorldPoint(12.5, 8.25);

        expect(point.x).toBe(12.5);
        expect(point.y).toBe(8.25);
    });

    it("is immutable", () => {
        const point = new WorldPoint(10, 20);

        expect(point.x).toBe(10);
        expect(point.y).toBe(20);
    });
});