import { StatusEnum } from "@/features/api/gen";
import ProgressBar from "@/features/ui/components/progress-bar";
import { useTaskStatus } from "@/hooks/use-task-status";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

type StepLoaderProps = {
    taskId: string;
    onComplete: () => void;
    onError: (error: string) => void;
}

const renderProgressText = (
    t: ReturnType<typeof useTranslation>['t'],
    importStatus: NonNullable<ReturnType<typeof useTaskStatus>>
) => {
    if (importStatus.progress !== null && importStatus.progress > 0) {
        return <p>{t('{{progress}}% imported', { progress: importStatus.progress })}</p>;
    }
    if (importStatus.currentMessage > 0 && !importStatus.hasKnownTotal) {
        return <p>{t('{{count}} messages imported', { count: importStatus.currentMessage })}</p>;
    }
    return null;
};

export const StepLoader = ({ taskId, onComplete, onError }: StepLoaderProps) => {
    const { t } = useTranslation();
    const importStatus = useTaskStatus(taskId)!;

    // Use refs to avoid stale closures without requiring stable callback props
    const onCompleteRef = useRef(onComplete);
    onCompleteRef.current = onComplete;
    const onErrorRef = useRef(onError);
    onErrorRef.current = onError;

    useEffect(() => {
        if (importStatus?.state === StatusEnum.SUCCESS) {
            onCompleteRef.current();
        } else if (importStatus?.state === StatusEnum.FAILURE) {
            const error = importStatus?.error || '';
            let errorKey = t('An error occurred while importing messages.');
            if (
                error.includes("AUTHENTICATIONFAILED") ||
                error.includes("IMAP authentication failed")
            ) {
                errorKey = t('Authentication failed. Please check your credentials and ensure you have enabled IMAP connections in your account.');
            }
            onErrorRef.current(errorKey);
        }
    }, [importStatus?.state, t]);

    return (
        <div className="task-loader">
            <Spinner size="lg" />
            <div className="task-loader__progress_resume">
                <p>{t('Importing...')}</p>
                {renderProgressText(t, importStatus)}
            </div>
            <ProgressBar progress={importStatus.progress} />
            {importStatus.state === StatusEnum.PROGRESS && <p>{t('You can close this window and continue using the app.')}</p>}
        </div>
    );
}
