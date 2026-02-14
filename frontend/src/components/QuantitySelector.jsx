// FIX: architecture_review.md — "Frontend Component Split"
// Extracted quantity selector from VendingMachine.jsx.

export default function QuantitySelector({
    selectedPads,
    availablePads,
    onIncrement,
    onDecrement,
}) {
    return (
        <div className="p-6 border-b border-gray-200">
            <p className="text-lg font-medium text-gray-700 mb-3">
                Select Quantity:
            </p>
            <div className="flex items-center justify-between bg-gray-50 p-4 rounded-lg">
                <button
                    className="w-10 h-10 flex items-center justify-center bg-white text-purple-600 rounded-full shadow-sm border border-gray-200 hover:bg-purple-50 transition-colors duration-200"
                    onClick={onDecrement}
                    disabled={selectedPads <= 1}
                    aria-label="Decrease quantity"
                >
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="h-5 w-5"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                    >
                        <path
                            fillRule="evenodd"
                            d="M3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"
                            clipRule="evenodd"
                        />
                    </svg>
                </button>
                <div className="flex flex-col items-center">
                    <p className="text-2xl font-bold text-gray-800">{selectedPads}</p>
                    <p className="text-sm text-gray-500">
                        pad{selectedPads > 1 ? "s" : ""} selected
                    </p>
                </div>
                <button
                    className="w-10 h-10 flex items-center justify-center bg-white text-purple-600 rounded-full shadow-sm border border-gray-200 hover:bg-purple-50 transition-colors duration-200"
                    onClick={onIncrement}
                    disabled={selectedPads >= 5 || selectedPads >= availablePads}
                    aria-label="Increase quantity"
                >
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="h-5 w-5"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                    >
                        <path
                            fillRule="evenodd"
                            d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z"
                            clipRule="evenodd"
                        />
                    </svg>
                </button>
            </div>
        </div>
    );
}
