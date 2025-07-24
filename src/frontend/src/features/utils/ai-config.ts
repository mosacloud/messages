
import { useConfigRetrieve } from "@/features/api/gen/config/config";
import { ConfigRetrieve200 } from "@/features/api/gen/models/config_retrieve200";


export const areAIFeaturesEnabled = (config?: ConfigRetrieve200): boolean => {
    return config?.AI_ENABLED === true;
}

export const isAISummaryEnabled = (config?: ConfigRetrieve200): boolean => {
    return areAIFeaturesEnabled(config) && config?.AI_FEATURE_SUMMARY_ENABLED === true;
}

// Hook to retrieve AI feature flags from config
export function useAIFeaturesConfig() {
    const { data: configData } = useConfigRetrieve();
    const config = configData?.data as ConfigRetrieve200 | undefined;
    return {
        areAIFeaturesEnabled : areAIFeaturesEnabled(config),
        isAISummaryEnabled: isAISummaryEnabled(config),
    };
}