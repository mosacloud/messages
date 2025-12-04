type ThreadItemSendersProps = {
    senders: readonly string[],
}

export const ThreadItemSenders = ({ senders }: ThreadItemSendersProps) => {
    return (
            <p className="thread-item__sender">
                {senders.join(', ')}
            </p>
    )
}
