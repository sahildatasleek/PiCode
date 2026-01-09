const AWS = require('aws-sdk');
const connect = new AWS.Connect();
const docClient = new AWS.DynamoDB.DocumentClient();

const tableName = process.env.QUEUETABLE;
const cacheTTL = parseInt(process.env.DYNAMODBMIN || '5'); // cache in minutes
const hoursRange = parseInt(process.env.HOURS || '1');      // fallback lookback
const instanceId = process.env.INSTANCEID;

exports.handler = async (event) => {
  console.log("Event:", JSON.stringify(event));

  const queueArn = event.Details?.Parameters?.queueARN;
  const channel = (event.Details?.Parameters?.channel || 'CHAT').toUpperCase();
  const queueId = getQueueId(queueArn);
  const now = Date.now();

  let queueAnswerTimeSec = 60; // default 1 minute = 60 seconds
  let cached = await getQueueInfo(queueId);

  // ✅ Step 1: Use cached value if fresh
  if (cached && (now - cached.timestamp) / 60000 < cacheTTL) {
    console.log("Using cached value (seconds):", cached.queueAnswerTime);
    const ewtMinutes = Math.round(cached.queueAnswerTime / 60);
    return { QUEUE_ANSWER_TIME: ewtMinutes.toString() };
  }

  // ✅ Step 2: Fetch fresh metrics
  console.log("Fetching fresh metrics...");
  queueAnswerTimeSec = await getEWT(queueId, channel, hoursRange);

  // ✅ Step 3: Save to DynamoDB as seconds
  await saveQueueInfo(queueId, queueAnswerTimeSec, now);

  // ✅ Step 4: Return to Connect as minutes
  const ewtMinutes = Math.round(queueAnswerTimeSec / 60);
  console.log("Returning EWT (minutes):", ewtMinutes);

  return { QUEUE_ANSWER_TIME: ewtMinutes.toString() };
};

// 🔹 Fetch combined EWT (seconds)
async function getEWT(queueId, channel, hoursRange) {
  let queueAnswerTimeSec = 60; // default 1 min = 60 seconds

  try {
    // Step 1: Try real-time metrics
    queueAnswerTimeSec = await getCurrentMetrics(queueId, channel);

    // Step 2: Fallback to historical data if needed
    if (queueAnswerTimeSec <= 60) {
      const historical = await getHistoricalMetrics(queueId, channel, hoursRange);
      if (historical > 0) queueAnswerTimeSec = historical;
    }
  } catch (err) {
    console.error("Error fetching metrics:", err);
  }

  // ✅ Cap between 60 seconds (1 min) and 1200 seconds (20 min)
  return Math.min(Math.max(queueAnswerTimeSec, 60), 1200);
}

// 🔹 Get live metrics
async function getCurrentMetrics(queueId, channel) {
  const params = {
    InstanceId: instanceId,
    Filters: { Queues: [queueId], Channels: [channel] },
    CurrentMetrics: [
      { Name: "CONTACTS_IN_QUEUE", Unit: "COUNT" },
      { Name: "OLDEST_CONTACT_AGE", Unit: "SECONDS" },
      { Name: "AGENTS_AVAILABLE", Unit: "COUNT" }
    ],
    Groupings: ["QUEUE"]
  };

  console.log("Current metric request:", JSON.stringify(params));
  const response = await connect.getCurrentMetricData(params).promise();
  console.log("Current metric response:", JSON.stringify(response));

  let contactsInQueue = 0, oldestContactAge = 0, agentsAvailable = 0;

  if (response.MetricResults?.length > 0) {
    const data = response.MetricResults[0].Collections;
    for (const metric of data) {
      const name = metric.Metric?.Name;
      const val = metric.Value || 0;
      if (name === "CONTACTS_IN_QUEUE") contactsInQueue = val;
      if (name === "OLDEST_CONTACT_AGE") oldestContactAge = val;
      if (name === "AGENTS_AVAILABLE") agentsAvailable = val;
    }
  }

  console.log(`contactsInQueue=${contactsInQueue}, oldestContactAge=${oldestContactAge}, agentsAvailable=${agentsAvailable}`);

  if (contactsInQueue > 0) {
    const avgHandleTimeSec = 180; // assume 3 minutes = 180 seconds
    const backlog = Math.max(contactsInQueue - agentsAvailable, 0);
    const estSeconds = oldestContactAge + backlog * avgHandleTimeSec;
    return estSeconds; // always in seconds
  }

  return 60; // default 1 minute = 60 seconds
}

// 🔹 Historical fallback
async function getHistoricalMetrics(queueId, channel, hoursRange) {
  const params = {
    InstanceId: instanceId,
    StartTime: getStartTime(hoursRange),
    EndTime: getEndTime(),
    Filters: { Queues: [queueId], Channels: [channel] },
    Groupings: ["QUEUE"],
    HistoricalMetrics: [
      { Name: "QUEUE_ANSWER_TIME", Statistic: "AVG", Unit: "SECONDS" }
    ]
  };

  console.log("Historical metric request:", JSON.stringify(params));
  const response = await connect.getMetricData(params).promise();
  console.log("Historical metric response:", JSON.stringify(response));

  const valueSec = response.MetricResults?.[0]?.Collections?.[0]?.Value || 60;
  return valueSec; // keep in seconds
}

// 🔹 Utility functions
function getQueueId(arn) {
  return arn?.split('/').pop() || "";
}

function getStartTime(hours) {
  const d = new Date();
  d.setHours(d.getHours() - parseInt(hours));
  d.setMinutes(d.getMinutes() - (d.getMinutes() % 5));
  d.setSeconds(0);
  d.setMilliseconds(0);
  return d;
}

function getEndTime() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - (d.getMinutes() % 5));
  d.setSeconds(0);
  d.setMilliseconds(0);
  return d;
}

async function saveQueueInfo(queueId, queueAnswerTimeSec, timestamp) {
  const params = {
    TableName: tableName,
    Item: {
      queueId,
      queueAnswerTime: queueAnswerTimeSec, // store seconds
      timestamp
    }
  };
  await docClient.put(params).promise();
}

async function getQueueInfo(queueId) {
  const params = {
    TableName: tableName,
    KeyConditionExpression: "#queueId = :queueId",
    ExpressionAttributeNames: { "#queueId": "queueId" },
    ExpressionAttributeValues: { ":queueId": queueId }
  };
  const res = await docClient.query(params).promise();
  return res.Items?.[0];
}