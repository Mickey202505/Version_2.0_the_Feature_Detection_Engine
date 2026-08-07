import { describe, expect, it } from "vitest";
import { FeatureType } from "../../src/domain/FeatureType";

describe("FeatureType", () => {
    it("defines the initial golf feature types", () => {
        expect(FeatureType.Green).toBe("Green");
        expect(FeatureType.Fringe).toBe("Fringe");
        expect(FeatureType.Tee).toBe("Tee");
        expect(FeatureType.Bunker).toBe("Bunker");
        expect(FeatureType.Fairway).toBe("Fairway");
    });
});