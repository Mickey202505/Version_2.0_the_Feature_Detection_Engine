import { FeatureType } from "./FeatureType";
import { Polygon } from "./Polygon";

export class Feature {
    public readonly type: FeatureType;
    public readonly polygon: Polygon;

    public constructor(type: FeatureType, polygon: Polygon) {
        this.type = type;
        this.polygon = polygon;
    }
}