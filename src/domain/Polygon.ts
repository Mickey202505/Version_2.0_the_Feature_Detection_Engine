import { WorldPoint } from "./WorldPoint";

export class Polygon {
    private readonly _points: readonly WorldPoint[];

    public constructor(points: readonly WorldPoint[]) {
        if (points.length < 3) {
            throw new Error("A polygon must contain at least three points.");
        }

        this._points = [...points];
    }

    public get points(): readonly WorldPoint[] {
        return this._points;
    }
}