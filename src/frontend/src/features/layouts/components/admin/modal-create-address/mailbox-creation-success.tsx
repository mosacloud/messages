import { MailboxAdminCreate } from "@/features/api/gen";
import { Banner } from "@/features/ui/components/banner";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@openfun/cunningham-react";
import { Trans, useTranslation } from "react-i18next";
import AdminMailboxCredentials from "../mailbox-credentials";

type MailboxCreationSuccessProps = {
    type: "personal" | "shared" | "redirect";
    mailbox: MailboxAdminCreate;
    onClose: () => void;
}

export const MailboxCreationSuccess = ({ type, mailbox, onClose }: MailboxCreationSuccessProps) => {
    const { t } = useTranslation();
    const mailboxAddress = mailbox.local_part + "@" + mailbox.domain_name;

    return (
        <div className="modal-create-address-success">
          <div className="modal-create-address__description">
                <div className="success-img-container">
                  <img src="/images/welcome.webp" alt="" />
                </div>
                {
                  type === "redirect" && (
                    <p><Trans i18nKey="create_address_modal.success.redirect" values={{mailbox:mailboxAddress}}/></p>
                  )
                }
                {
                  type === "shared" && (
                    <p><Trans i18nKey="create_address_modal.success.shared" values={{mailbox:mailboxAddress}}/></p>
                  )
                }
                {
                  type === "personal" && (
                    <>
                      <p><Trans i18nKey="create_address_modal.success.personal" values={{mailbox:mailboxAddress}}/></p>
                      {
                        mailbox.one_time_password ? (
                          <AdminMailboxCredentials mailbox={mailbox} />
                      ) : (
                        <Banner type="warning" icon={<Icon name="info" type={IconType.OUTLINED} />}>
                          {t('create_address_modal.success.credential_info')}
                        </Banner>
                      )}
                    </>
                  )
                }
            </div>
            <Button onClick={onClose} color="primary">{t('actions.close')}</Button>
        </div>
    )
}
