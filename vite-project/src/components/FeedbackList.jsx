import React, { useState, useEffect } from 'react';
import supabase from '../supabase';

export default function FeedbackList() {
  const [feedbacks, setFeedbacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedStatus, setSelectedStatus] = useState('all');
  const [selectedMachine, setSelectedMachine] = useState('all');
  const [machines, setMachines] = useState([]);

  useEffect(() => {
    fetchFeedbacks();
    fetchMachines();
  }, []);

  const fetchMachines = async () => {
    const { data, error } = await supabase
      .from('vending_machines')
      .select('machine_id, location');
    if (!error) {
      setMachines(data);
    }
  };

  const fetchFeedbacks = async () => {
    let query = supabase
      .from('feedback')
      .select(`
        *,
        vending_machines (
          location
        )
      `)
      .order('timestamp', { ascending: false });

    if (selectedStatus !== 'all') {
      query = query.eq('status', selectedStatus);
    }
    if (selectedMachine !== 'all') {
      query = query.eq('machine_id', selectedMachine);
    }

    const { data, error } = await query;
    if (error) {
      console.error('Error fetching feedback:', error);
    } else {
      setFeedbacks(data);
    }
    setLoading(false);
  };

  const updateFeedbackStatus = async (feedbackId, newStatus) => {
    const { error } = await supabase
      .from('feedback')
      .update({ status: newStatus })
      .eq('feedback_id', feedbackId);

    if (!error) {
      fetchFeedbacks();
    }
  };

  const getStatusColor = (status) => {
    const colors = {
      new: 'bg-blue-100 text-blue-800',
      in_review: 'bg-yellow-100 text-yellow-800',
      closed: 'bg-green-100 text-green-800'
    };
    return colors[status] || 'bg-gray-100 text-gray-800';
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-700"></div>
      </div>
    );
  }

  const renderStars = (rating) => {
    return [...Array(5)].map((_, index) => (
      <svg
        key={index}
        className={`w-4 h-4 ${index < rating ? 'text-yellow-400' : 'text-gray-300'}`}
        fill="currentColor"
        viewBox="0 0 20 20"
      >
        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
      </svg>
    ));
  };

  return (
    <div className="bg-white rounded-xl shadow-lg p-6">
      <div className="flex flex-col sm:flex-row justify-between items-center mb-6 gap-4">
        <h2 className="text-2xl font-bold text-purple-800">Customer Feedback</h2>
        <div className="flex gap-4">
          <select
            className="bg-white border border-gray-300 rounded-md px-3 py-2 text-sm"
            value={selectedMachine}
            onChange={(e) => {
              setSelectedMachine(e.target.value);
              fetchFeedbacks();
            }}
          >
            <option value="all">All Machines</option>
            {machines.map((machine) => (
              <option key={machine.machine_id} value={machine.machine_id}>
                {machine.location} ({machine.machine_id})
              </option>
            ))}
          </select>
          <select
            className="bg-white border border-gray-300 rounded-md px-3 py-2 text-sm"
            value={selectedStatus}
            onChange={(e) => {
              setSelectedStatus(e.target.value);
              fetchFeedbacks();
            }}
          >
            <option value="all">All Status</option>
            <option value="new">New</option>
            <option value="in_review">In Review</option>
            <option value="closed">Closed</option>
          </select>
        </div>
      </div>

      <div className="grid gap-4">
        {feedbacks.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            No feedback found for the selected filters.
          </div>
        ) : (
          feedbacks.map((feedback) => (
            <div
              key={feedback.feedback_id}
              className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow"
            >
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <div className="flex">{renderStars(feedback.rating)}</div>
                  <span className="text-sm text-gray-500">|</span>
                  <span className="text-sm text-gray-600">
                    {feedback.vending_machines?.location || 'Unknown Location'} ({feedback.machine_id})
                  </span>
                </div>
                <span className="text-sm text-gray-500">{formatDate(feedback.timestamp)}</span>
              </div>
              
              {feedback.comment && (
                <p className="text-gray-700 my-2">{feedback.comment}</p>
              )}

              <div className="flex justify-between items-center mt-3">
                <span className={`px-3 py-1 rounded-full text-sm ${getStatusColor(feedback.status)}`}>
                  {feedback.status.replace('_', ' ')}
                </span>
                <div className="flex gap-2">
                  {feedback.status !== 'in_review' && (
                    <button
                      onClick={() => updateFeedbackStatus(feedback.feedback_id, 'in_review')}
                      className="text-sm bg-yellow-100 text-yellow-700 px-3 py-1 rounded-md hover:bg-yellow-200 transition-colors"
                    >
                      Mark In Review
                    </button>
                  )}
                  {feedback.status !== 'closed' && (
                    <button
                      onClick={() => updateFeedbackStatus(feedback.feedback_id, 'closed')}
                      className="text-sm bg-green-100 text-green-700 px-3 py-1 rounded-md hover:bg-green-200 transition-colors"
                    >
                      Mark Closed
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}