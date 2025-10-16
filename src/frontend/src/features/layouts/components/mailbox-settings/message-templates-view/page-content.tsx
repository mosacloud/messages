import { useMailboxContext } from "@/features/providers/mailbox";
import { MessageTemplateDataGrid } from "./message-template-data-grid";

export const ManageMessageTemplatesViewPageContent = () => {
  const { selectedMailbox } = useMailboxContext();

  return (
    <div className="admin-page__content">
      <MessageTemplateDataGrid mailbox={selectedMailbox!} />
    </div>
  );
};
