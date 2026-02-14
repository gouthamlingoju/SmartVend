// FIX: architecture_review.md — "Frontend Component Split"
// Extracted success and dispensing popups from VendingMachine.jsx.

export default function SuccessPopup({
    showPopup,
    isDispensing,
    selectedPads,
    dispensedPads,
    onDone,
}) {
    if (isDispensing) {
        return (
            <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50">
                <div className="bg-white p-6 rounded-lg shadow-lg text-center">
                    <h2 className="text-xl font-bold text-yellow-600">
                        Dispensing Pads...
                    </h2>
                    <p className="text-gray-600">
                        {dispensedPads} / {selectedPads} Pad(s) dispensed
                    </p>
                </div>
            </div>
        );
    }

    if (!showPopup) return null;

    return (
        <div
            className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 z-50"
            aria-modal="true"
            role="dialog"
        >
            <div className="bg-white p-6 rounded-lg shadow-xl max-w-sm w-full text-center">
                <div className="w-16 h-16 mx-auto bg-green-100 rounded-full flex items-center justify-center mb-4">
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="h-10 w-10 text-green-600"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                    >
                        <path
                            fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd"
                        />
                    </svg>
                </div>
                <h2 className="text-xl font-bold text-gray-800 mb-2">
                    Payment Successful!
                </h2>
                <p className="text-gray-600 mb-6">
                    Please collect your {selectedPads} pad
                    {selectedPads > 1 ? "s" : ""} from the dispenser.
                </p>
                <button
                    className="bg-purple-600 hover:bg-purple-700 text-white px-6 py-3 rounded-md transition-colors duration-200 w-full"
                    onClick={onDone}
                >
                    Done
                </button>
            </div>
        </div>
    );
}
