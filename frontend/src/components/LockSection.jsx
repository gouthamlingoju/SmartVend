// FIX: architecture_review.md — "Frontend Component Split"
// Extracted lock/unlock section from VendingMachine.jsx.
import { useState } from "react";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

export default function LockSection({
    machine,
    clientId,
    locked,
    setLocked,
    lockedByOther,
    setLockedByOther,
    lockedRemaining,
    setLockedRemaining,
    formatSeconds,
    accessCodeInput,
    setAccessCodeInput,
    setLockedUntil,
    handleLockCode,
    countdownRef,
}) {
    const handleUnlock = async () => {
        try {
            const res = await fetch(
                `${BACKEND_URL}/api/machine/${machine.machine_id}/unlock`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ client_id: clientId }),
                }
            );
            if (!res.ok) {
                const e = await res.json().catch(() => ({ detail: "unlock failed" }));
                return alert(e.detail || e.message || "Unlock failed");
            }
            await res.json();
            setLocked(false);
            setLockedUntil(null);
            setAccessCodeInput("");
            setLockedByOther(false);
            if (countdownRef.current) {
                clearInterval(countdownRef.current);
                countdownRef.current = null;
            }
            alert("Unlocked successfully");
        } catch (err) {
            console.error(err);
            alert("Unlock failed");
        }
    };

    if (locked) {
        return (
            <div className="space-y-3">
                <p className="text-green-600 text-sm">
                    Locked — time left:{" "}
                    <span className="font-mono ml-1">
                        {formatSeconds(lockedRemaining)}
                    </span>
                </p>
                <div className="mt-2">
                    <button
                        onClick={handleUnlock}
                        className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-md transition-colors duration-200"
                    >
                        Unlock
                    </button>
                </div>
            </div>
        );
    }

    if (lockedByOther) {
        return (
            <div className="space-y-3">
                <p className="text-amber-600 text-sm">
                    This machine is locked by another user — time left:{" "}
                    <span className="font-mono ml-1">
                        {formatSeconds(lockedRemaining)}
                    </span>
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-3">
            <p className="text-gray-500 text-sm">Enter Code shown on machine</p>
            <div className="flex items-center justify-center mt-2 space-x-2">
                <input
                    value={accessCodeInput}
                    onChange={(e) => setAccessCodeInput(e.target.value)}
                    className="px-3 py-2 border rounded-md w-48"
                    placeholder="XXXXXX"
                />
                <button
                    onClick={handleLockCode}
                    className="bg-purple-600 text-white px-3 py-2 rounded-md"
                >
                    Lock
                </button>
            </div>
        </div>
    );
}
