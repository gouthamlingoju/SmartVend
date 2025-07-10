import React from 'react';

export default function Welcome({ onUser, onAdmin }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-purple-200 via-blue-100 to-pink-100">
      <div className="bg-white rounded-2xl shadow-lg p-10 flex flex-col items-center">
        <h1 className="text-3xl font-bold text-purple-700 mb-8">Welcome to SmartVend</h1>
        <div className="flex gap-8">
          <button className="bg-purple-600 hover:bg-purple-700 text-white px-8 py-4 rounded-lg text-xl font-semibold" onClick={onUser}>User</button>
          <button className="bg-gray-700 hover:bg-gray-800 text-white px-8 py-4 rounded-lg text-xl font-semibold" onClick={onAdmin}>Admin</button>
        </div>
      </div>
    </div>
  );
}
